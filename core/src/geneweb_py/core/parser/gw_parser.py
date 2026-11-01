"""
Parser principal GeneWeb

Ce module implémente le parser principal qui orchestre le parsing lexical
et syntaxique pour créer une représentation complète des données généalogiques.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import chardet

from ..event import EventType, WitnessKind
from ..exceptions import (
    GeneWebEncodingError,
    GeneWebParseError,
    ParseWarning,
)
from ..family import ChildSex, FamilyQualifier, MarriageStatus
from ..models import Date, Family, FamilyEvent, FamilyEventType, Genealogy, Person
from ..person import (
    AccessLevel,
    Gender,
    ParentRole,
    Relation,
    RelationType,
    Title,
)
from .lexical import LexicalParser, Token, TokenType
from .place_tokens import death_marker, mot_end, place_run_end, texte_libre
from .place_tokens import join_tokens_text as _join_tokens_text
from .streaming import (
    StreamingGeneWebParser,
    estimate_memory_usage,
    should_use_streaming,
)
from .syntax import BlockType, SyntaxNode, SyntaxParser

logger = logging.getLogger(__name__)

# Agrégats `comm` famille : borne mémoire (DoS lors d'une ligne ou séquence géante).
_FAMILY_COMM_AGGREGATE_MAX_CHARS = 512 * 1024
_FAMILY_COMM_MAX_FRAGMENTS = 10000

# Autres accumulations texte (notes, occupations, métadonnées) : même discipline.
_TEXT_AGGREGATE_MAX_CHARS = 512 * 1024
_TEXT_AGGREGATE_MAX_FRAGMENTS = 10000

# Bloc ``fevt`` (gwplus) : plafonds événements / témoins (DoS).
_FEVT_MAX_EVENTS_PER_BLOCK = 500
_FEVT_MAX_WITNESSES_PER_BLOCK = 200


# Alias GEDCOM acceptés dans un bloc pevt (le tag d'origine reste dans event_type_raw)
_PEVT_TAG_ALIASES = {"bapm": EventType.BAPTISM}

# Tokens dédiés du lexer pour des tags d'événements standard dans un bloc pevt
_PEVT_DEDICATED_TOKENS = (TokenType.OCCU, TokenType.BURI, TokenType.CREM)


def _tokens_line_text(tokens: List[Token], start: int) -> Tuple[str, int]:
    """Reconstitue le texte d'une ligne à partir de ses tokens.

    Les espaces d'origine sont déduits des positions (un espace unique si les tokens
    ne sont pas contigus), ce qui préserve la ponctuation collée aux mots.

    Returns:
        (texte de la ligne, index du NEWLINE/fin de bloc qui la termine)
    """
    parts: List[str] = []
    prev_end = -1
    i = start
    while i < len(tokens) and tokens[i].type not in (TokenType.NEWLINE, TokenType.EOF):
        tok = tokens[i]
        if parts and tok.position != prev_end:
            parts.append(" ")
        parts.append(tok.value)
        prev_end = tok.position + len(tok.value)
        i += 1
    return "".join(parts), i


def _content_lines(tokens: List[Token], with_end: bool = False) -> List[int]:
    """Numéros de ligne (triés) portant du contenu.

    Les fins de bloc (``end``, ``end pevt``...) sont exclues sauf ``with_end``.
    """
    return sorted(
        {
            t.line_number
            for t in tokens
            if t.line_number
            and t.type not in (TokenType.NEWLINE, TokenType.EOF)
            and (with_end or not t.type.name.startswith("END"))
        }
    )


def _node_line_span(
    node: SyntaxNode, with_end: bool = False
) -> Tuple[Optional[int], Optional[int]]:
    """Première et dernière ligne source d'un nœud (enfants compris)."""
    lines = _content_lines(node.tokens, with_end)
    for child in node.children:
        lines.extend(_content_lines(child.tokens, with_end))
    return (min(lines), max(lines)) if lines else (None, None)


def _mark_person_defined(
    person: Person, start: Optional[int], end: Optional[int]
) -> None:
    """Fixe la provenance d'une personne au premier bloc qui la définit."""
    if person.start_line is None:
        person.start_line = start
        person.end_line = end


def _assign_event_end_lines(events: List[Any], tokens: List[Token]) -> None:
    """Calcule ``end_line`` : dernière ligne de contenu avant l'événement suivant."""
    lines = _content_lines(tokens)
    started = [e for e in events if e.start_line is not None]
    started.sort(key=lambda e: e.start_line)
    for idx, event in enumerate(started):
        limit = started[idx + 1].start_line if idx + 1 < len(started) else None
        inside = [
            n for n in lines if n >= event.start_line and (limit is None or n < limit)
        ]
        event.end_line = max(inside) if inside else event.start_line


def _attach_wnote(witnesses: List[Any], line_text: str) -> bool:
    """Rattache une ligne ``wnote …`` au dernier témoin ; faux s'il n'y en a pas."""
    if not witnesses:
        return False
    _, _, texte = line_text.partition(" ")
    witnesses[-1]["note"] = texte.strip()
    return True


def _is_bang(token: Token) -> bool:
    """Le ``!`` qui précède la date de baptême."""
    return token.type == TokenType.UNKNOWN and token.value == "!"


def _is_line_start_note(tokens: List[Token], i: int) -> bool:
    """Vrai si tokens[i] est un mot ``note`` en début de ligne (hors ``#``)."""
    tok = tokens[i]
    return (
        tok.type == TokenType.IDENTIFIER
        and tok.value == "note"
        and (i == 0 or tokens[i - 1].type == TokenType.NEWLINE)
    )


def _bounded_append_text_fragment(
    parts: List[str],
    agg_len: int,
    fragment: str,
    inter_fragment_sep_len: int,
    max_fragments: int,
    max_aggregate_chars: int,
    log_context: str,
) -> Tuple[int, bool]:
    """Ajoute un fragment à une liste avec plafonds fragments / caractères.

    Utilisé pour éviter une croissance non bornée (entrée hostile) lors du
    concaténage de tokens en note, occupation ou métadonnées.

    Args:
        parts: Liste des fragments déjà acceptés (modifiée en place).
        agg_len: Longueur cumulée actuelle (séparateurs inclus selon la règle).
        fragment: Texte à ajouter.
        inter_fragment_sep_len: Longueur du séparateur entre fragments (1 = espace,
            0 = concaténation directe).
        max_fragments: Nombre maximal de fragments.
        max_aggregate_chars: Taille maximale agrégée (caractères).
        log_context: Libellé court pour le journal (ex. ``notes bloc``).

    Returns:
        Tuple (nouvelle longueur agrégée, True si une limite a été atteinte et
        que l'appelant doit arrêter d'alimenter cette agrégation).
    """
    if len(parts) >= max_fragments:
        logger.debug(
            "%s: tronqué, limite de fragments %s atteinte",
            log_context,
            max_fragments,
        )
        return agg_len, True
    sep_len = inter_fragment_sep_len if parts else 0
    if agg_len + sep_len + len(fragment) > max_aggregate_chars:
        logger.debug(
            "%s: tronqué, limite d'agrégat %s caractères atteinte",
            log_context,
            max_aggregate_chars,
        )
        return agg_len, True
    parts.append(fragment)
    return agg_len + sep_len + len(fragment), False


class GeneWebParser:
    """Parser principal pour les fichiers .gw

    Ce parser orchestre le processus complet de parsing :
    1. Lecture et détection d'encodage
    2. Tokenisation lexicale
    3. Parsing syntaxique
    4. Construction des modèles de données

    Optimisations de performance :
    - Mode streaming automatique pour les gros fichiers (>10MB)
    - Cache LRU pour les patterns regex
    - __slots__ pour réduire l'empreinte mémoire
    - Parsing ligne par ligne au lieu de tout charger en mémoire
    """

    def __init__(
        self,
        validate: bool = True,
        stream_mode: Optional[bool] = None,
        streaming_threshold_mb: float = 10.0,
        strict: bool = True,
        use_multipass: bool = False,
    ):
        """Initialise le parser

        Args:
            validate: Si True, valide la cohérence des données après parsing
            stream_mode: Si True, force le mode streaming.
                Si None, détection automatique.
            streaming_threshold_mb: Seuil en MB pour activer le streaming
                automatiquement.
            strict: Si True, lève une exception à la première erreur. Si False,
                parsing gracieux.
            use_multipass: Si True, utilise le parser multi-passes
                (recommandé pour fichiers complexes).
        """
        self.validate = validate
        self.stream_mode = stream_mode
        self.streaming_threshold_mb = streaming_threshold_mb
        self.strict = strict
        self.use_multipass = use_multipass
        self.lexical_parser: Optional[LexicalParser] = None
        self.syntax_parser = SyntaxParser()
        self.tokens: List[Token] = []
        self.syntax_nodes: List[SyntaxNode] = []

        # Collecteur d'erreurs pour parsing gracieux
        from ..exceptions import GeneWebErrorCollector

        self.error_collector = GeneWebErrorCollector(strict=strict)

    def parse_file(self, file_path: Union[str, Path]) -> Genealogy:
        """Parse un fichier .gw avec optimisation automatique

        Détecte automatiquement la taille du fichier et choisit le mode approprié :
        - Mode normal pour les petits fichiers (<10MB)
        - Mode streaming pour les gros fichiers (>10MB)

        Args:
            file_path: Chemin vers le fichier .gw

        Returns:
            Instance de Genealogy avec toutes les données parsées

        Raises:
            GeneWebParseError: En cas d'erreur de parsing
            GeneWebEncodingError: En cas de problème d'encodage
        """
        file_path = Path(file_path)
        # Valider l'extension du fichier
        if file_path.suffix.lower() not in [".gw", ".gwplus"]:
            raise GeneWebParseError(
                f"Extension de fichier invalide: {file_path.suffix}"
            )

        if not file_path.exists():
            raise GeneWebParseError(f"Fichier non trouvé: {file_path}")

        # Déterminer si on doit utiliser le mode streaming
        use_streaming = self.stream_mode
        if use_streaming is None:
            use_streaming = should_use_streaming(file_path, self.streaming_threshold_mb)

        try:
            if use_streaming:
                # Mode streaming pour gros fichiers
                return self._parse_file_streaming(file_path)
            else:
                # Mode normal pour petits fichiers
                # Lire le fichier avec détection d'encodage
                content, encoding = self._read_file_with_encoding(file_path)

                # Parser le contenu
                genealogy = self.parse_string(
                    content, filename=str(file_path), encoding=encoding
                )

                # Ajouter les métadonnées du fichier
                genealogy.metadata.source_file = str(file_path)
                genealogy.metadata.encoding = encoding

                return genealogy

        except Exception as e:
            if isinstance(e, (GeneWebParseError, GeneWebEncodingError)):
                raise
            raise GeneWebParseError(
                f"Erreur lors du parsing de {file_path}: {e}"
            ) from e  # noqa: E501

    def _parse_file_streaming(self, file_path: Path) -> Genealogy:
        """Parse un fichier en mode streaming (pour gros fichiers)

        Args:
            file_path: Chemin vers le fichier

        Returns:
            Instance de Genealogy
        """
        streaming_parser = StreamingGeneWebParser(validate=self.validate)

        # Collecter les tokens en streaming
        self.tokens = list(streaming_parser.parse_file_streaming(file_path))

        # Parsing syntaxique (identique)
        self.syntax_nodes = self.syntax_parser.parse(self.tokens)

        # Construction des modèles (identique)
        genealogy = self._build_genealogy()
        self._copy_parse_errors_to_genealogy(genealogy)

        # Validation si demandée
        if self.validate:
            errors = genealogy.validate_consistency()
            if errors:
                error_messages = [str(error) for error in errors]
                raise GeneWebParseError(
                    f"Erreurs de validation détectées: {'; '.join(error_messages)}"
                )

        genealogy.metadata.source_file = str(file_path)
        return genealogy

    def parse_string(
        self,
        content: str,
        filename: Optional[str] = None,
        encoding: Optional[str] = None,
    ) -> Genealogy:
        """Parse une chaîne de caractères contenant du .gw

        Args:
            content: Contenu du fichier .gw
            filename: Nom du fichier (pour les erreurs)

        Returns:
            Instance de Genealogy avec toutes les données parsées
        """
        # Chaîne vide → généalogie vide
        if content is None or content.strip() == "":
            from ..genealogy import Genealogy

            genealogy = Genealogy()
            if filename:
                genealogy.metadata.source_file = filename
            if encoding:
                genealogy.metadata.encoding = encoding
            return genealogy

        # CRLF en lecture binaire (p.ex. Git autocrlf) : le lexer ne retire pas \r seul.
        content = content.replace("\r\n", "\n").replace("\r", "\n")

        # Validation de lignes en tête si validation active (détection de lignes non reconnues)  # noqa: E501
        if self.validate and content:
            allowed_starts = {
                "fam",
                "notes",
                "rel",
                "pevt",
                "fevt",
                "end",
                "beg",
                "wit",
                "wnote",
                "src",
                "comm",
                "+",
                "-",
                "#",
                "notes-db",
                "page-ext",
                "wizard-note",
                "encoding:",
                "gwplus",
                "husb",
                "wife",
                "cbp",
                "csrc",
                "marr",
                "div",
                "sep",
                "eng",
                "note",
                "(*",
            }
            inside_block = False
            current_block = None

            for line_num, raw_line in enumerate(content.splitlines(), 1):
                line = raw_line.strip()
                if not line:
                    continue

                # Autoriser les lignes enfants '-' et commentaires '#'
                if line.startswith("#") or line.startswith("-"):
                    continue

                word = line.split()[0].lower()

                # Commentaires bloc GeneWeb (* ... *)
                if line.startswith("(*"):
                    continue

                # Gestion des blocs spéciaux
                if word in {"notes-db", "page-ext", "wizard-note", "notes"}:
                    inside_block = True
                    current_block = word
                    continue
                elif word == "end" and inside_block and current_block:
                    # Vérifier si c'est la fin du bloc actuel
                    if f"end {current_block}" in line.lower():
                        inside_block = False
                        current_block = None
                    continue

                # Si on est à l'intérieur d'un bloc, ne pas valider le contenu
                if inside_block:
                    continue

                # Validation seulement pour les lignes en dehors des blocs
                # Vérifier le mot avec et sans les deux-points (ex: "wit:" ou "wit")
                word_without_colon = word.rstrip(":")
                if (
                    word not in allowed_starts
                    and word_without_colon not in allowed_starts
                ):
                    raise GeneWebParseError(
                        "Contenu .gw invalide: ligne non reconnue", line_number=line_num
                    )

        # Tokenisation lexicale
        self.lexical_parser = LexicalParser(content, filename)
        self.tokens = self.lexical_parser.tokenize()

        # Parsing syntaxique
        self.syntax_nodes = self.syntax_parser.parse(self.tokens)

        # Contenu invalide: aucun bloc reconnu (sauf si seulement des commentaires)
        # Seulement quand la validation est activée
        if self.validate:
            has_content_blocks = any(
                node.type
                in [
                    BlockType.FAMILY,
                    BlockType.PERSON_EVENTS,
                    BlockType.FAMILY_EVENTS,
                    BlockType.NOTES,
                    BlockType.RELATIONS,
                    BlockType.DATABASE_NOTES,
                    BlockType.EXTENDED_PAGE,
                    BlockType.WIZARD_NOTE,
                ]
                for node in self.syntax_nodes
            )

            # Si pas de blocs de contenu, vérifier s'il y a des commentaires
            if not has_content_blocks:
                has_comments = any(
                    token.type in (TokenType.COMMENT, TokenType.BLOCK_COMMENT)
                    for token in self.tokens
                )
                if not has_comments:
                    raise GeneWebParseError(
                        "Contenu .gw invalide: aucun bloc reconnu", line_number=1
                    )

        # Construction des modèles de données
        genealogy = self._build_genealogy()
        self._copy_parse_errors_to_genealogy(genealogy)

        if self.validate:
            errors = genealogy.validate_consistency()
            if errors:
                error_messages = [str(error) for error in errors]
                raise GeneWebParseError(
                    f"Erreurs de validation détectées: {'; '.join(error_messages)}"
                )

        # Encoder la métadonnée d'encodage si fourni
        if encoding:
            genealogy.metadata.encoding = encoding
        return genealogy

    def _copy_parse_errors_to_genealogy(self, genealogy: Genealogy) -> None:
        """Recopie les erreurs collectées pendant le build vers la généalogie."""
        from ..exceptions import GeneWebError

        if not self.error_collector.has_errors():
            return
        for err in self.error_collector.get_errors():
            if isinstance(err, GeneWebError):
                genealogy.add_validation_error(err)

    def _get_or_create_person(
        self,
        last_name: str,
        first_name: str,
        occurrence_num: Optional[int],
        persons: dict,
        genealogy: Genealogy,
        gender: Gender = Gender.UNKNOWN,
    ) -> str:
        """Crée ou récupère une personne avec gestion intelligente des numéros
        d'occurrence.

        Args:
            last_name: Nom de famille
            first_name: Prénom
            occurrence_num: Numéro d'occurrence (None si non spécifié)
            persons: Dictionnaire des personnes existantes
            genealogy: Objet Genealogy
            gender: Sexe de la personne

        Returns:
            ID de la personne créée ou récupérée
        """
        # Si occurrence_num est spécifié, l'utiliser directement
        if occurrence_num is not None:
            person_id = f"{last_name}_{first_name}_{occurrence_num}"
            if person_id not in persons:
                person = Person(
                    last_name=last_name,
                    first_name=first_name,
                    occurrence_number=occurrence_num,
                    gender=gender,
                )
                persons[person_id] = person
                # Ajouter ou mettre à jour la personne dans la généalogie
                genealogy.add_or_update_person(person)
            else:
                # La personne existe, mettre à jour son sexe si nécessaire
                existing = persons[person_id]
                if gender != Gender.UNKNOWN and existing.gender == Gender.UNKNOWN:
                    existing.gender = gender
            return person_id

        # Sinon, chercher une personne existante avec occurrence 0
        base_id = f"{last_name}_{first_name}_0"
        if base_id in persons:
            # La personne existe, mettre à jour son sexe si nécessaire
            existing = persons[base_id]
            if gender != Gender.UNKNOWN and existing.gender == Gender.UNKNOWN:
                existing.gender = gender
            return base_id

        # Si aucune personne n'existe, créer avec occurrence 0
        person = Person(
            last_name=last_name,
            first_name=first_name,
            occurrence_number=0,
            gender=gender,
        )
        # Déduplication stricte: si existe déjà côté persons ou genealogy, réutiliser
        if base_id not in persons:
            persons[base_id] = person
        # Ajouter ou mettre à jour la personne
        genealogy.add_or_update_person(person)
        return base_id

    def _read_file_with_encoding(self, file_path: Path) -> Tuple[str, str]:
        """Lit un fichier avec détection automatique d'encodage optimisée

        Optimisation: Essaye UTF-8 d'abord, utilise chardet seulement si nécessaire

        Args:
            file_path: Chemin vers le fichier

        Returns:
            Tuple (contenu, encodage détecté)
        """
        try:
            # Lire le fichier en binaire pour détecter l'encodage
            with open(file_path, "rb") as f:
                raw_data = f.read()

            # Essayer d'abord UTF-8 (plus commun maintenant, évite chardet)
            try:
                content = raw_data.decode("utf-8")
                return content, "utf-8"
            except UnicodeDecodeError:
                pass

            # Détecter l'encodage avec chardet seulement si UTF-8 échoue
            result = chardet.detect(raw_data[:8192])  # Échantillon pour optimisation
            detected_encoding = result["encoding"]
            confidence = result["confidence"]

            if detected_encoding is not None and confidence >= 0.7:
                # Si la confiance est élevée, utiliser l'encodage détecté
                try:
                    content = raw_data.decode(detected_encoding)
                    return content, detected_encoding
                except UnicodeDecodeError:
                    pass

            # Essayer ISO-8859-1 en dernier recours
            try:
                content = raw_data.decode("iso-8859-1")
                return content, "iso-8859-1"
            except UnicodeDecodeError:
                pass

            # Si rien ne fonctionne, utiliser l'encodage détecté avec remplacement d'erreurs  # noqa: E501
            content = raw_data.decode(detected_encoding or "utf-8", errors="replace")
            return content, detected_encoding or "utf-8"

        except Exception as e:
            if isinstance(e, GeneWebEncodingError):
                raise
            raise GeneWebEncodingError(
                f"Erreur lors de la lecture du fichier: {e}"
            ) from e  # noqa: E501

    def get_memory_estimate(self, file_path: Union[str, Path]) -> dict:
        """Estime l'utilisation mémoire pour parser un fichier

        Args:
            file_path: Chemin vers le fichier

        Returns:
            Dictionnaire avec les estimations de mémoire
        """
        return estimate_memory_usage(file_path)

    def _build_genealogy(self) -> Genealogy:
        """Construit l'objet Genealogy à partir des nœuds syntaxiques

        Returns:
            Instance de Genealogy complète
        """
        # Router vers le parser multi-passes si activé
        if self.use_multipass:
            try:
                from .multipass_parser import MultiPassParser
            except ImportError:
                logger.warning(
                    "use_multipass=True mais multipass_parser est absent "
                    "(module non inclus) ; utilisation du mode incrémental."
                )
            else:
                content = None
                if self.lexical_parser and hasattr(self.lexical_parser, "text"):
                    content = self.lexical_parser.text

                multipass = MultiPassParser(
                    content=content,
                    gene_web_parser=self,
                )
                return multipass.parse_syntax_nodes(self.syntax_nodes)

        return self._build_genealogy_incremental(
            self.syntax_nodes,
            second_cross_ref_pass=False,
        )

    def _build_genealogy_incremental(
        self,
        syntax_nodes: List[SyntaxNode],
        second_cross_ref_pass: bool = False,
    ) -> Genealogy:
        """Construit Genealogy à partir d'une liste de nœuds syntaxiques.

        Args:
            syntax_nodes: Arborescence produite par le parser syntaxique.
            second_cross_ref_pass: Si True, relance la mise à jour des références
                croisées après fusion finale des personnes (mode multi-passes).

        Returns:
            Instance de Genealogy complète
        """
        genealogy = Genealogy()

        # Dictionnaires pour stocker les entités pendant la construction
        persons: Dict[str, Person] = {}  # ID -> Person
        families: Dict[str, Family] = {}  # ID -> Family

        # Contexte pour associer fevt et enfants à la famille précédente
        current_family = None  # Référence à la dernière famille créée

        # Parser chaque bloc
        for node in syntax_nodes:
            if node.type == BlockType.FAMILY:
                # Vérifier si c'est un vrai bloc famille (token FAM) ou des
                # enfants (token BEG)
                if node.tokens and node.tokens[0].type == TokenType.FAM:
                    # C'est un bloc famille normal
                    current_family = self._parse_family_block(
                        node, persons, families, genealogy
                    )
                elif node.tokens and node.tokens[0].type == TokenType.BEG:
                    # C'est un bloc enfants (beg/end) à associer à la famille courante
                    if current_family is not None:
                        end_lines = _content_lines(node.tokens, with_end=True)
                        for child_node in node.children:
                            end_lines += _content_lines(child_node.tokens, True)
                        if end_lines:
                            current_family.end_line = max(
                                end_lines + [current_family.end_line or 0]
                            )
                        for child_node in node.children:
                            self._parse_child(
                                child_node, current_family, persons, genealogy
                            )
                else:
                    # Bloc famille sans indication claire, le traiter normalement
                    current_family = self._parse_family_block(
                        node, persons, families, genealogy
                    )
            elif node.type == BlockType.NOTES:
                self._parse_notes_block(node, persons, genealogy)
            elif node.type == BlockType.RELATIONS:
                self._parse_relations_block(node, persons, genealogy)
            elif node.type == BlockType.PERSON_EVENTS:
                self._parse_person_events_block(node, persons, genealogy)
            elif node.type == BlockType.FAMILY_EVENTS:
                # Parser les événements familiaux (fevt) et les rattacher à la famille
                self._parse_family_events_block(
                    node, persons, families, genealogy, current_family
                )
            elif node.type == BlockType.DATABASE_NOTES:
                self._parse_database_notes_block(node, genealogy)
            elif node.type == BlockType.EXTENDED_PAGE:
                self._parse_extended_page_block(node, persons, genealogy)
            elif node.type == BlockType.WIZARD_NOTE:
                self._parse_wizard_note_block(node, persons, genealogy)

        # Mettre à jour les références croisées
        genealogy._update_cross_references()

        # Ajouter ou mettre à jour toutes les personnes créées (témoins,
        # relations, etc.)
        for person in persons.values():
            genealogy.add_or_update_person(person)

        if second_cross_ref_pass:
            genealogy._update_cross_references()

        return genealogy

    def _parse_family_block(
        self, node: SyntaxNode, persons: dict, families: dict, genealogy: Genealogy
    ) -> Optional[Family]:
        """Parse un bloc famille et construit les objets Person et Family

        Returns:
            La famille créée, ou None si aucune famille n'a été créée
        """

        # Extraire les informations du bloc
        tokens = node.tokens

        # Parser la ligne fam avec une approche plus robuste
        family_info = self._parse_family_line(tokens)

        # Créer les personnes si elles n'existent pas
        husband_id = None
        wife_id = None

        if family_info["husband_name"] and family_info["husband_firstname"]:
            husband_id = self._get_or_create_person(
                family_info["husband_name"],
                family_info["husband_firstname"],
                family_info["husband_occurrence"],
                persons,
                genealogy,
                Gender.MALE,
            )
            # Appliquer les informations personnelles du mari
            husband = persons[husband_id]
            if family_info["husband_public_name"]:
                husband.public_name = family_info["husband_public_name"]
            if family_info["husband_first_name_alias"]:
                husband.first_name_alias = family_info["husband_first_name_alias"]
            if family_info["husband_birth_date"]:
                husband.birth_date = family_info["husband_birth_date"]
            if family_info["husband_death_date"]:
                husband.death_date = family_info["husband_death_date"]
            if family_info["husband_obviously_dead"]:
                husband.is_obviously_dead = True
            if family_info["husband_young_death"]:
                husband.is_young_death = True
            if family_info["husband_birth_place"]:
                husband.birth_place = family_info["husband_birth_place"]
            if family_info["husband_death_place"]:
                husband.death_place = family_info["husband_death_place"]
            if family_info["husband_birth_source"]:
                husband.birth_source = family_info["husband_birth_source"]
            if family_info["husband_death_source"]:
                husband.death_source = family_info["husband_death_source"]
            if family_info["husband_baptism_date"]:
                husband.baptism_date = family_info["husband_baptism_date"]
            if family_info["husband_baptism_place"]:
                husband.baptism_place = family_info["husband_baptism_place"]
            if family_info["husband_baptism_source"]:
                husband.baptism_source = family_info["husband_baptism_source"]
            if family_info["husband_burial_place"]:
                husband.burial_place = family_info["husband_burial_place"]
            if family_info["husband_burial_source"]:
                husband.burial_source = family_info["husband_burial_source"]
            if family_info["husband_occupation"]:
                husband.occupation = family_info["husband_occupation"]
            if family_info["husband_access_level"]:
                husband.access_level = family_info["husband_access_level"]
            if family_info["husband_nickname"]:
                husband.nickname = family_info["husband_nickname"]
            if family_info["husband_surname_alias"]:
                husband.surname_alias = family_info["husband_surname_alias"]
            if family_info["husband_general_alias"]:
                husband.general_alias = family_info["husband_general_alias"]
            if family_info["husband_image_path"]:
                husband.image_path = family_info["husband_image_path"]
            if family_info["husband_titles"]:
                for title in family_info["husband_titles"]:
                    husband.add_title(title)

        if family_info["wife_name"] and family_info["wife_firstname"]:
            wife_id = self._get_or_create_person(
                family_info["wife_name"],
                family_info["wife_firstname"],
                family_info["wife_occurrence"],
                persons,
                genealogy,
                Gender.FEMALE,
            )
            # Appliquer les informations personnelles de la femme
            wife = persons[wife_id]
            if family_info["wife_public_name"]:
                wife.public_name = family_info["wife_public_name"]
            if family_info["wife_first_name_alias"]:
                wife.first_name_alias = family_info["wife_first_name_alias"]
            if family_info["wife_birth_date"]:
                wife.birth_date = family_info["wife_birth_date"]
            if family_info["wife_death_date"]:
                wife.death_date = family_info["wife_death_date"]
            if family_info["wife_obviously_dead"]:
                wife.is_obviously_dead = True
            if family_info["wife_young_death"]:
                wife.is_young_death = True
            if family_info["wife_birth_place"]:
                wife.birth_place = family_info["wife_birth_place"]
            if family_info["wife_death_place"]:
                wife.death_place = family_info["wife_death_place"]
            if family_info["wife_birth_source"]:
                wife.birth_source = family_info["wife_birth_source"]
            if family_info["wife_death_source"]:
                wife.death_source = family_info["wife_death_source"]
            if family_info["wife_baptism_date"]:
                wife.baptism_date = family_info["wife_baptism_date"]
            if family_info["wife_baptism_place"]:
                wife.baptism_place = family_info["wife_baptism_place"]
            if family_info["wife_baptism_source"]:
                wife.baptism_source = family_info["wife_baptism_source"]
            if family_info["wife_burial_place"]:
                wife.burial_place = family_info["wife_burial_place"]
            if family_info["wife_burial_source"]:
                wife.burial_source = family_info["wife_burial_source"]
            if family_info["wife_occupation"]:
                wife.occupation = family_info["wife_occupation"]
            if family_info["wife_access_level"]:
                wife.access_level = family_info["wife_access_level"]
            if family_info["wife_nickname"]:
                wife.nickname = family_info["wife_nickname"]
            if family_info["wife_surname_alias"]:
                wife.surname_alias = family_info["wife_surname_alias"]
            if family_info["wife_general_alias"]:
                wife.general_alias = family_info["wife_general_alias"]
            if family_info["wife_image_path"]:
                wife.image_path = family_info["wife_image_path"]
            if family_info["wife_titles"]:
                for title in family_info["wife_titles"]:
                    wife.add_title(title)

        # La ligne fam existe : la famille aussi, même si les deux conjoints sont
        # inconnus (``fam ? ? + ? ?``), sinon enfants et événements sont perdus (R13)
        if tokens:
            family_id = f"FAM_{len(families) + 1:03d}"
            family = Family(
                family_id=family_id,
                husband_id=husband_id,
                wife_id=wife_id,
                spouses_unknown=not (husband_id or wife_id),
                marriage_date=family_info["marriage_date"],
                marriage_place=family_info["marriage_place"],
                marriage_status=family_info["marriage_status"],
                divorce_date=family_info["divorce_date"],
                is_separated=family_info["is_separated"],
            )

            family.start_line, family.end_line = _node_line_span(node, with_end=True)
            header_line = tokens[0].line_number if tokens else None
            for spouse_id in (husband_id, wife_id):
                if spouse_id:
                    _mark_person_defined(persons[spouse_id], header_line, header_line)

            # Parser les enfants
            for child_node in node.children:
                self._parse_child(child_node, family, persons, genealogy)

            # Modificateurs de ligne (#sep / #div), témoins, sources et commentaires
            self._apply_family_extra_tokens(family, tokens, persons, genealogy)

            families[family_id] = family
            genealogy.add_family(family)
            return family

        return None

    def _apply_family_extra_tokens(
        self,
        family: Family,
        tokens: List[Token],
        persons: dict,
        genealogy: Genealogy,
    ) -> None:
        """Applique les tokens famille hors ligne époux/enfants (#div, wit, src, comm).

        Les modificateurs inline sont traités dans `_parse_family_line`; cette passe
        couvre les lignes suivantes (témoins multi-lignes, etc.).
        """
        i = 0
        en_tete = True  # avant le ``beg`` des enfants
        comm_fin = -1  # dernière ligne de commentaire
        while i < len(tokens):
            tok = tokens[i]
            if tok.type == TokenType.WIT:
                next_i, witness_id, witness_type, witness_kind = (
                    self._parse_witness_person(tokens, i, persons, genealogy)
                )
                if witness_id:
                    family.add_witness(witness_id, witness_type, witness_kind)
                i = next_i
                continue
            if tok.type == TokenType.SEP:
                family.marriage_status = MarriageStatus.SEPARATED
                family.is_separated = True
                i += 1
                if i < len(tokens) and tokens[i].type == TokenType.DASH:
                    i += 1
                elif i < len(tokens) and tokens[i].type == TokenType.DATE:
                    family.divorce_date = Date.parse_with_fallback(tokens[i].value)
                    i += 1
                continue
            if tok.type == TokenType.DIV:
                family.marriage_status = MarriageStatus.DIVORCED
                i += 1
                if i < len(tokens) and tokens[i].type == TokenType.DASH:
                    i += 1
                elif i < len(tokens) and tokens[i].type == TokenType.DATE:
                    family.divorce_date = Date.parse_with_fallback(tokens[i].value)
                    i += 1
                continue
            if tok.type == TokenType.NM:
                family.marriage_status = MarriageStatus.NOT_MARRIED
                i += 1
                continue
            if tok.type == TokenType.ENG:
                family.marriage_status = MarriageStatus.ENGAGED
                i += 1
                continue
            if tok.type == TokenType.MS:
                i += 1
                if i < len(tokens) and tokens[i].type in (
                    TokenType.IDENTIFIER,
                    TokenType.STRING,
                ):
                    value, i = self._parse_short_source(tokens, i)
                    family.marriage_source = value
                continue
            if tok.type in (
                TokenType.NSCK,
                TokenType.NSCKM,
                TokenType.NOMENT,
                TokenType.BANNS,
                TokenType.CONTRACT,
                TokenType.LICENSE,
            ):
                qualifier_map = {
                    TokenType.NSCK: FamilyQualifier.NO_SEX_CHECK,
                    TokenType.NSCKM: FamilyQualifier.NO_SEX_CHECK_MARRIAGE,
                    TokenType.NOMENT: FamilyQualifier.NO_MENTION,
                    TokenType.BANNS: FamilyQualifier.BANNS,
                    TokenType.CONTRACT: FamilyQualifier.CONTRACT,
                    TokenType.LICENSE: FamilyQualifier.LICENSE,
                }
                family.family_qualifiers.append(qualifier_map[tok.type])
                i += 1
                continue
            if tok.type == TokenType.MARR:
                i += 1
                if i < len(tokens) and tokens[i].type == TokenType.DATE:
                    family.marriage_date = Date.parse_with_fallback(tokens[i].value)
                    i += 1
                if i < len(tokens) and tokens[i].type == TokenType.P:
                    i += 1
                    if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                        family.marriage_place = tokens[i].value
                        i += 1
                continue
            if tok.type == TokenType.DIV_EVENT:
                i += 1
                family.marriage_status = MarriageStatus.DIVORCED
                if i < len(tokens) and tokens[i].type == TokenType.DATE:
                    family.divorce_date = Date.parse_with_fallback(tokens[i].value)
                    i += 1
                if i < len(tokens) and tokens[i].type == TokenType.P:
                    i += 1
                    if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                        i += 1
                continue
            if tok.type == TokenType.SEP_EVENT:
                i += 1
                family.marriage_status = MarriageStatus.SEPARATED
                family.is_separated = True
                if i < len(tokens) and tokens[i].type == TokenType.DATE:
                    family.divorce_date = Date.parse_with_fallback(tokens[i].value)
                    i += 1
                if i < len(tokens) and tokens[i].type == TokenType.P:
                    i += 1
                    if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                        i += 1
                continue
            if tok.type == TokenType.SRC:
                i += 1
                src_start = i
                while i < len(tokens) and tokens[i].type not in (
                    TokenType.NEWLINE,
                    TokenType.EOF,
                ):
                    i += 1
                if i > src_start:
                    family.family_source = _join_tokens_text(tokens[src_start:i])
                continue
            if tok.type == TokenType.COMM:
                i += 1
                parts: List[str] = []
                agg_len = 0
                comm_debut = i
                while i < len(tokens) and tokens[i].type not in (
                    TokenType.NEWLINE,
                    TokenType.WIT,
                    TokenType.SRC,
                    TokenType.BEG,
                    TokenType.END,
                ):
                    frag = tokens[i].value
                    agg_len, stop = _bounded_append_text_fragment(
                        parts,
                        agg_len,
                        frag,
                        inter_fragment_sep_len=1,
                        max_fragments=_FAMILY_COMM_MAX_FRAGMENTS,
                        max_aggregate_chars=_FAMILY_COMM_AGGREGATE_MAX_CHARS,
                        log_context="Commentaire famille `comm`",
                    )
                    if stop:
                        break
                    i += 1
                if parts:
                    family.add_comment(texte_libre(tokens[comm_debut:i], len(parts)))
                    comm_fin = tokens[i - 1].line_number
                continue
            if tok.type == TokenType.BEG:
                en_tete = False
            elif (
                en_tete
                and i > 0
                and tokens[i - 1].type == TokenType.NEWLINE
                and tok.type
                not in (
                    TokenType.NEWLINE,
                    TokenType.WHITESPACE,
                    TokenType.END,
                    TokenType.EOF,
                )
            ):
                # Texte nu (R13) : suite du commentaire de la ligne d'avant, sinon
                # nouveau commentaire de famille
                ligne = tok.line_number
                texte, i = _tokens_line_text(tokens, i)
                if tok.type == TokenType.WNOTE and _attach_wnote(
                    family.witnesses, texte
                ):
                    continue
                if comm_fin == ligne - 1 and family.comments:
                    family.comments[-1] += "\n" + texte
                else:
                    family.add_comment(texte)
                comm_fin = ligne
                continue
            i += 1

    def _parse_family_line(self, tokens: List[Token]) -> dict:
        """Parse une ligne fam et extrait toutes les informations

        Format: fam LastName FirstName [infos perso] + LastName FirstName
            [infos perso]

        Returns:
            Dictionnaire avec toutes les informations extraites
        """
        result: Dict[str, Any] = {
            "husband_name": None,
            "husband_firstname": None,
            "husband_occurrence": None,
            "husband_public_name": None,
            "husband_first_name_alias": None,
            "husband_birth_date": None,
            "husband_death_date": None,
            "husband_birth_place": None,
            "husband_death_place": None,
            "husband_birth_source": None,
            "husband_death_source": None,
            "husband_baptism_date": None,
            "husband_baptism_place": None,
            "husband_baptism_source": None,
            "husband_burial_place": None,
            "husband_burial_source": None,
            "husband_occupation": None,
            "husband_access_level": None,
            "husband_nickname": None,
            "husband_surname_alias": None,
            "husband_general_alias": None,
            "husband_image_path": None,
            "wife_name": None,
            "wife_firstname": None,
            "wife_occurrence": None,
            "wife_public_name": None,
            "wife_first_name_alias": None,
            "wife_birth_date": None,
            "wife_death_date": None,
            "wife_birth_place": None,
            "wife_death_place": None,
            "wife_birth_source": None,
            "wife_death_source": None,
            "wife_baptism_date": None,
            "wife_baptism_place": None,
            "wife_baptism_source": None,
            "wife_burial_place": None,
            "wife_burial_source": None,
            "wife_occupation": None,
            "wife_access_level": None,
            "wife_nickname": None,
            "wife_surname_alias": None,
            "wife_general_alias": None,
            "wife_image_path": None,
            "husband_obviously_dead": False,
            "husband_young_death": False,
            "wife_obviously_dead": False,
            "wife_young_death": False,
            "husband_titles": [],
            "wife_titles": [],
            "marriage_date": None,
            "marriage_place": None,
            "marriage_status": MarriageStatus.MARRIED,
            "divorce_date": None,
            "is_separated": False,
        }

        i = 0
        current_person = "husband"  # 'husband' ou 'wife'

        def consume_sep_div(i_: int) -> int:
            """Consomme #sep / #div (+ date ou '-') après une époux/se."""
            while i_ < len(tokens):
                tok = tokens[i_]
                if tok.type == TokenType.SEP:
                    result["marriage_status"] = MarriageStatus.SEPARATED
                    result["is_separated"] = True
                    i_ += 1
                    if i_ < len(tokens) and tokens[i_].type == TokenType.DASH:
                        i_ += 1
                    elif i_ < len(tokens) and tokens[i_].type == TokenType.DATE:
                        result["divorce_date"] = Date.parse_with_fallback(
                            tokens[i_].value
                        )
                        i_ += 1
                    continue
                if tok.type == TokenType.DIV:
                    result["marriage_status"] = MarriageStatus.DIVORCED
                    result["divorce_date"] = None
                    i_ += 1
                    if i_ < len(tokens) and tokens[i_].type == TokenType.DASH:
                        i_ += 1
                    elif i_ < len(tokens) and tokens[i_].type == TokenType.DATE:
                        result["divorce_date"] = Date.parse_with_fallback(
                            tokens[i_].value
                        )
                        i_ += 1
                    continue
                if tok.type == TokenType.DASH:
                    # ``- [DivorceDate]`` : divorcés, date facultative
                    result["marriage_status"] = MarriageStatus.DIVORCED
                    i_ += 1
                    if i_ < len(tokens) and tokens[i_].type == TokenType.DATE:
                        result["divorce_date"] = Date.parse_with_fallback(
                            tokens[i_].value
                        )
                        i_ += 1
                    continue
                if tok.type == TokenType.NM:
                    result["marriage_status"] = MarriageStatus.NOT_MARRIED
                    i_ += 1
                    continue
                if tok.type == TokenType.ENG:
                    result["marriage_status"] = MarriageStatus.ENGAGED
                    i_ += 1
                    continue
                break
            return i_

        while i < len(tokens):
            token = tokens[i]

            # La ligne fam s'arrête au saut de ligne : la suite (src, comm…) n'est
            # pas une donnée d'époux/se
            if token.type in (TokenType.NEWLINE, TokenType.EOF):
                break

            # Passer le token 'fam'
            if token.type == TokenType.FAM:
                i += 1
                continue

            # Séparateur de mariage - passer à la femme
            elif token.type == TokenType.PLUS:
                current_person = "wife"
                i += 1
                # La date de mariage suit immédiatement le + (ex: +25/11/1728)
                if (
                    i < len(tokens)
                    and tokens[i].type == TokenType.DATE
                    and not result["marriage_date"]
                ):
                    result["marriage_date"] = Date.parse_with_fallback(tokens[i].value)
                    i += 1
                i = consume_sep_div(i)
                continue

            # Modificateurs union (#sep / #div / #nm / #eng) hors position époux/se
            elif token.type in (
                TokenType.SEP,
                TokenType.DIV,
                TokenType.NM,
                TokenType.ENG,
            ):
                i = consume_sep_div(i)
                continue

            # ``- [DivorceDate]`` seulement sur la ligne fam : les lignes suivantes
            # du bloc (src, comm…) peuvent contenir des tirets sans rapport.
            elif (
                token.type == TokenType.DASH
                and token.line_number == tokens[0].line_number
            ):
                i = consume_sep_div(i)
                continue

            # Date de mariage (#marr ou événement mariage gwplus)
            elif token.type == TokenType.MARR:
                i += 1
                if i < len(tokens) and tokens[i].type == TokenType.DATE:
                    result["marriage_date"] = Date.parse_with_fallback(tokens[i].value)
                    i += 1
                if i < len(tokens) and tokens[i].type == TokenType.P:
                    i += 1
                    if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                        result["marriage_place"] = tokens[i].value
                        i += 1
                continue

            # Nom de famille
            elif (
                token.type == TokenType.IDENTIFIER
                and not result[f"{current_person}_name"]
            ):
                result[f"{current_person}_name"] = token.value
                i += 1
                continue

            # Prénom
            elif (
                token.type == TokenType.IDENTIFIER
                and result[f"{current_person}_name"]
                and not result[f"{current_person}_firstname"]
            ):
                result[f"{current_person}_firstname"] = token.value
                i += 1
                continue

            # Marqueurs de décès ``od`` / ``mj`` (natifs sans ``#``, ou ``#od`` / ``#mj``)
            # une fois nom et prénom lus : sinon ``od`` serait pris pour l'épouse.
            elif (
                result[f"{current_person}_firstname"]
                and death_marker(token) is not None
            ):
                key = "obviously_dead" if death_marker(token) == "od" else "young_death"
                result[f"{current_person}_{key}"] = True
                i += 1
                continue

            # Si le mari est déjà défini (nom+prénom) et qu'on rencontre un nouvel IDENTIFIER,  # noqa: E501
            # l'interpréter comme début des infos de l'épouse (format inline sans '+').
            elif (
                token.type == TokenType.IDENTIFIER
                and current_person == "husband"
                and result["husband_name"]
                and result["husband_firstname"]
                and not result["wife_name"]
            ):
                current_person = "wife"
                # Ne pas consommer ici; la boucle reprendra et tombera sur le cas 'Nom de famille'  # noqa: E501
                continue

            # Nom public (PublicName)
            elif (
                token.type == TokenType.PAREN_OPEN and result[f"{current_person}_name"]
            ):
                parts: List[str] = []
                i += 1
                while i < len(tokens) and tokens[i].type != TokenType.PAREN_CLOSE:
                    parts.append(tokens[i].value.replace("_", " "))
                    i += 1
                if i < len(tokens) and tokens[i].type == TokenType.PAREN_CLOSE:
                    i += 1
                if parts:
                    result[f"{current_person}_public_name"] = " ".join(parts)
                continue

            # Alias de prénom {FirstNameAlias}
            elif (
                token.type == TokenType.BRACE_OPEN
                and result[f"{current_person}_firstname"]
            ):
                parts = []
                i += 1
                while i < len(tokens) and tokens[i].type != TokenType.BRACE_CLOSE:
                    parts.append(tokens[i].value.replace("_", " "))
                    i += 1
                if i < len(tokens) and tokens[i].type == TokenType.BRACE_CLOSE:
                    i += 1
                if parts:
                    result[f"{current_person}_first_name_alias"] = " ".join(parts)
                continue

            # Titres [TitleName:Type:Place:StartDate:EndDate:Nth]
            elif (
                token.type == TokenType.BRACKET_OPEN
                and result[f"{current_person}_firstname"]
            ):
                title, i = self._parse_title_bracket(tokens, i)
                if title is not None:
                    result[f"{current_person}_titles"].append(title)
                continue

            # Numéro d'occurrence (après le prénom)
            elif (
                token.type == TokenType.NUMBER
                and result[f"{current_person}_firstname"]
                and result[f"{current_person}_occurrence"] is None
            ):
                # Extraire le numéro du token (ex: ".1" -> 1)
                occurrence_str = token.value.lstrip(".")
                try:
                    result[f"{current_person}_occurrence"] = int(occurrence_str)
                except ValueError:
                    result[f"{current_person}_occurrence"] = 0
                i += 1
                continue

            # Date (peut être naissance ou décès selon le contexte)
            elif _is_bang(token):
                i += 1
                continue

            elif token.type == TokenType.DATE and i > 0 and _is_bang(tokens[i - 1]):
                result[f"{current_person}_baptism_date"] = Date.parse_with_fallback(
                    token.value
                )
                i += 1
                continue

            elif token.type == TokenType.DATE:
                # Si c'est la première date, c'est probablement la naissance
                if result[f"{current_person}_birth_date"] is None:
                    result[f"{current_person}_birth_date"] = Date.parse_with_fallback(
                        token.value
                    )
                # Sinon c'est probablement le décès
                elif result[f"{current_person}_death_date"] is None:
                    result[f"{current_person}_death_date"] = Date.parse_with_fallback(
                        token.value
                    )
                i += 1
                continue

            # Lieu de naissance (#bp)
            elif token.type == TokenType.BP:
                i += 1
                value, i = self._parse_short_place(tokens, i)
                if value:
                    result[f"{current_person}_birth_place"] = value
                continue

            # Lieu de décès (#dp)
            elif token.type == TokenType.DP:
                i += 1
                value, i = self._parse_short_place(tokens, i)
                if value:
                    result[f"{current_person}_death_place"] = value
                continue

            # Occupation (#occu)
            elif token.type == TokenType.OCCU:
                i += 1
                occupation_parts: List[str] = []
                occ_agg = 0
                while i < len(tokens) and tokens[i].type in [
                    TokenType.IDENTIFIER,
                    TokenType.STRING,
                    TokenType.PAREN_OPEN,
                    TokenType.PAREN_CLOSE,
                    TokenType.UNKNOWN,
                ]:
                    # Remplacer les underscores par des espaces pour l'affichage
                    occ_seg = tokens[i].value.replace("_", " ")
                    occ_agg, stop = _bounded_append_text_fragment(
                        occupation_parts,
                        occ_agg,
                        occ_seg,
                        inter_fragment_sep_len=0,
                        max_fragments=_TEXT_AGGREGATE_MAX_FRAGMENTS,
                        max_aggregate_chars=_TEXT_AGGREGATE_MAX_CHARS,
                        log_context="Occupation ligne fam",
                    )
                    i += 1
                    if stop:
                        break
                if occupation_parts:
                    result[f"{current_person}_occupation"] = "".join(occupation_parts)
                continue

            # Accès privé (#apriv)
            elif token.type == TokenType.APRIV:
                result[f"{current_person}_access_level"] = AccessLevel.PRIVATE
                i += 1
                continue

            # Accès public (#apubl)
            elif token.type == TokenType.APUBL:
                result[f"{current_person}_access_level"] = AccessLevel.PUBLIC
                i += 1
                continue

            # Surnom (#nick)
            elif token.type == TokenType.NICK:
                i += 1
                if i < len(tokens) and tokens[i].type in (
                    TokenType.IDENTIFIER,
                    TokenType.STRING,
                ):
                    result[f"{current_person}_nickname"] = tokens[i].value.replace(
                        "_", " "
                    )
                    i += 1
                continue

            # Alias de nom de famille (#salias)
            elif token.type == TokenType.SALIAS:
                i += 1
                if i < len(tokens) and tokens[i].type in (
                    TokenType.IDENTIFIER,
                    TokenType.STRING,
                ):
                    result[f"{current_person}_surname_alias"] = tokens[i].value
                    i += 1
                continue

            # Alias général (#alias)
            elif token.type == TokenType.ALIAS:
                i += 1
                if i < len(tokens) and tokens[i].type in (
                    TokenType.IDENTIFIER,
                    TokenType.STRING,
                ):
                    result[f"{current_person}_general_alias"] = tokens[i].value
                    i += 1
                continue

            # Chemin image (#image)
            elif token.type == TokenType.IMAGE:
                i += 1
                image_parts = []
                # Consume tokens until newline/eof/modifier
                while i < len(tokens) and tokens[i].type not in (
                    TokenType.NEWLINE,
                    TokenType.EOF,
                    TokenType.WIT,
                    TokenType.SRC,
                    TokenType.COMM,
                    TokenType.NOTE,
                ):
                    # Stop at known modifiers
                    if tokens[i].type in (
                        TokenType.NICK,
                        TokenType.SALIAS,
                        TokenType.ALIAS,
                        TokenType.BP,
                        TokenType.DP,
                        TokenType.OCCU,
                        TokenType.APUBL,
                        TokenType.APRIV,
                    ):
                        break
                    image_parts.append(tokens[i].value)
                    i += 1
                if image_parts:
                    result[f"{current_person}_image_path"] = "".join(image_parts)
                continue

            # Source naissance (#bs)
            elif token.type == TokenType.BS:
                i += 1
                value, i = self._parse_short_source(tokens, i)
                if value:
                    result[f"{current_person}_birth_source"] = value.replace("_", " ")
                continue

            # Source décès (#ds)
            elif token.type == TokenType.DS:
                i += 1
                value, i = self._parse_short_source(tokens, i)
                if value:
                    result[f"{current_person}_death_source"] = value.replace("_", " ")
                continue

            # Lieu baptême (#pp)
            elif token.type == TokenType.PP:
                i += 1
                value, i = self._parse_short_place(tokens, i)
                if value:
                    result[f"{current_person}_baptism_place"] = value.replace("_", " ")
                continue

            # Source baptême (#ps)
            elif token.type == TokenType.PS:
                i += 1
                value, i = self._parse_short_source(tokens, i)
                if value:
                    result[f"{current_person}_baptism_source"] = value.replace("_", " ")
                continue

            # Lieu inhumation (#rp)
            elif token.type == TokenType.RP:
                i += 1
                value, i = self._parse_short_place(tokens, i)
                if value:
                    result[f"{current_person}_burial_place"] = value.replace("_", " ")
                continue

            # Source inhumation (#rs)
            elif token.type == TokenType.RS:
                i += 1
                value, i = self._parse_short_source(tokens, i)
                if value:
                    result[f"{current_person}_burial_source"] = value.replace("_", " ")
                continue

            # Source du mariage (#ms) : un mot, jamais le nom de l'épouse
            elif token.type == TokenType.MS:
                i += 1
                fin = mot_end(tokens, i)
                if fin > i:
                    value = _join_tokens_text(tokens[i:fin])
                    result["marriage_source"] = value.replace("_", " ")
                    i = fin
                continue

            # Lieu de mariage (#mp)
            # GW Plus: le lieu est de la forme Ville,_CodePostal,_Région,_Pays
            # On ne consomme que les UNKNOWN "," (virgules), pas "#" ni les autres.
            elif token.type == TokenType.MP:
                i += 1
                place_parts: List[str] = []
                fin = place_run_end(tokens, i)
                if fin > i:
                    place_parts.append(_join_tokens_text(tokens[i:fin]))
                    i = fin
                if place_parts:
                    result["marriage_place"] = "".join(place_parts)
                continue

            # Modificateur GW Plus inconnu (ex: #ms url, #ps url) :
            # tokenise en UNKNOWN("#") + IDENTIFIER — on consomme jusqu'au nom de l'épouse
            elif token.type == TokenType.UNKNOWN and token.value == "#":
                if i + 1 < len(tokens) and tokens[i + 1].type == TokenType.IDENTIFIER:
                    i += 2  # sauter "#" et le nom du modificateur (ex: "ms")
                    while i < len(tokens):
                        t = tokens[i]
                        if t.type in (TokenType.NEWLINE, TokenType.EOF):
                            break
                        if t.type == TokenType.UNKNOWN and t.value == "#":
                            break  # prochain modificateur inconnu
                        if t.type in (
                            TokenType.MP,
                            TokenType.NM,
                            TokenType.ENG,
                            TokenType.SEP,
                            TokenType.DIV,
                            TokenType.SRC,
                            TokenType.S,
                            TokenType.BP,
                            TokenType.DP,
                            TokenType.OCCU,
                        ):
                            break
                        # Deux IDENTIFIER consécutifs = nom de l'épouse si suivis
                        # de NEWLINE/EOF ou d'un modificateur connu
                        if (
                            t.type == TokenType.IDENTIFIER
                            and i + 1 < len(tokens)
                            and tokens[i + 1].type == TokenType.IDENTIFIER
                        ):
                            j = i + 2
                            if j < len(tokens) and tokens[j].type == TokenType.NUMBER:
                                j += 1
                            after_type = (
                                tokens[j].type if j < len(tokens) else TokenType.EOF
                            )
                            if after_type in (
                                TokenType.NEWLINE,
                                TokenType.EOF,
                                TokenType.BP,
                                TokenType.DP,
                                TokenType.OCCU,
                                TokenType.APUBL,
                                TokenType.APRIV,
                                TokenType.OD,
                                TokenType.MJ,
                                TokenType.BURI,
                                TokenType.CREM,
                                TokenType.SRC,
                            ):
                                break
                        i += 1
                else:
                    i += 1
                continue

            # Autres tokens
            else:
                i += 1

        # Convention GeneWeb : un nom ou un prénom valant exactement ``?`` n'est pas
        # une clé de personne (``? ?``, ``? ?.0``…) : conjoint inconnu, aucune
        # personne créée (sinon tous les inconnus fusionneraient en une seule).
        # ``???``, ``_???`` ou ``???.1`` sont en revanche de vraies personnes.
        for role in ("husband", "wife"):
            if "?" in (result[f"{role}_name"], result[f"{role}_firstname"]):
                result[f"{role}_name"] = None
                result[f"{role}_firstname"] = None

        return result

    def _parse_child(
        self,
        child_node: SyntaxNode,
        family: Family,
        persons: dict,
        genealogy: Genealogy,
    ) -> None:
        """Parse un enfant dans un bloc famille"""
        tokens = child_node.tokens

        if not tokens or tokens[0].type != TokenType.DASH:
            return

        # Extraire les informations de l'enfant
        sex = ChildSex.UNKNOWN
        last_name = None
        first_name = None
        occurrence_num = None

        i = 1  # Passer le tire

        # Sexe de l'enfant (h ou f comme identifiant ou token spécial)
        if i < len(tokens) and (
            (tokens[i].type == TokenType.IDENTIFIER and tokens[i].value in ["h", "f"])
            or tokens[i].type in [TokenType.H, TokenType.F]
        ):
            if tokens[i].type == TokenType.H or (
                tokens[i].type == TokenType.IDENTIFIER and tokens[i].value == "h"
            ):
                sex = ChildSex.MALE
            else:
                sex = ChildSex.FEMALE
            i += 1

        # Nom et prénom de l'enfant
        # Si un seul IDENTIFIER: c'est le prénom, le nom vient du père
        # Si deux IDENTIFIER: c'est NOM Prénom
        if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
            first_identifier_value = tokens[i].value
            i += 1

            # Vérifier s'il y a un deuxième IDENTIFIER
            if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                # Deux identifiants: NOM Prénom
                last_name = first_identifier_value
                first_name = tokens[i].value
                i += 1
            else:
                # Un seul identifiant: c'est le Prénom, pas le nom
                first_name = first_identifier_value
                last_name = None  # Sera pris du père

        # Numéro d'occurrence (après le prénom)
        if i < len(tokens) and tokens[i].type == TokenType.NUMBER:
            occurrence_str = tokens[i].value.lstrip(".")
            try:
                occurrence_num = int(occurrence_str)
            except ValueError:
                occurrence_num = 0
            i += 1

        if first_name:
            # Utiliser le nom de famille du père si pas spécifié
            if not last_name:
                if family.husband_id:
                    husband = genealogy.find_person_by_id(family.husband_id)
                    if husband:
                        last_name = husband.last_name

                # Si toujours pas de nom, utiliser un nom par défaut
                if not last_name:
                    last_name = "UNKNOWN"

            # Utiliser la nouvelle méthode de déduplication
            child_id = self._get_or_create_person(
                last_name,
                first_name,
                occurrence_num,
                persons,
                genealogy,
                (
                    Gender.MALE
                    if sex == ChildSex.MALE
                    else Gender.FEMALE
                    if sex == ChildSex.FEMALE
                    else Gender.UNKNOWN
                ),
            )

            child_line = tokens[0].line_number
            _mark_person_defined(persons[child_id], child_line, child_line)

            # Parser les informations personnelles supplémentaires (occupation, etc.)
            i = self._parse_inline_personal_info(tokens, i, persons[child_id])

            # Ajouter l'enfant à la famille
            family.add_child(child_id, sex)

    def _parse_notes_block(
        self, node: SyntaxNode, persons: dict, genealogy: Genealogy
    ) -> None:
        """Parse un bloc notes et ajoute les notes à la personne correspondante"""
        tokens = node.tokens

        # Extraire le nom de la personne
        if (
            len(tokens) >= 3
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.IDENTIFIER
        ):
            last_name = tokens[1].value
            first_name = tokens[2].value

            person_id = f"{last_name}_{first_name}_0"

            # Créer la personne si elle n'existe pas
            if person_id not in persons:
                person = Person(
                    last_name=last_name, first_name=first_name, gender=Gender.UNKNOWN
                )
                persons[person_id] = person
                genealogy.add_or_update_person(person)

            # Extraire le contenu des notes
            notes_content: List[str] = []
            notes_tokens: List[Token] = []
            notes_agg = 0
            notes_stop = False
            in_content = False

            for token in tokens:
                if token.type == TokenType.BEG:
                    in_content = True
                    continue
                elif token.type == TokenType.END_NOTES:
                    break
                elif in_content and token.type not in [
                    TokenType.NEWLINE,
                    TokenType.WHITESPACE,
                ]:
                    notes_agg, notes_stop = _bounded_append_text_fragment(
                        notes_content,
                        notes_agg,
                        token.value,
                        inter_fragment_sep_len=1,
                        max_fragments=_TEXT_AGGREGATE_MAX_FRAGMENTS,
                        max_aggregate_chars=_TEXT_AGGREGATE_MAX_CHARS,
                        log_context="Bloc notes",
                    )
                    if not notes_stop:
                        notes_tokens.append(token)
                    if notes_stop:
                        break

            if notes_content:
                persons[person_id].add_note(
                    texte_libre(notes_tokens, len(notes_content))
                )

    def _parse_pevt_comment_line(
        self, comment_value: str, person_id: str
    ) -> Optional[Any]:
        """Parse une ligne commentaire de bloc pevt en PersonalEvent.

        Format attendu : #eventtype [date] [#p place] [#s source]
        Le token COMMENT contient la ligne entière sans le '#' initial.

        Args:
            comment_value: Valeur du token COMMENT (ex: '#grad 1/6/1985 #p Paris')
            person_id: Identifiant unique de la personne

        Returns:
            PersonalEvent ou None si non reconnue
        """
        import re as _re

        from ..event import EventType, PersonalEvent

        # Vérifier que la ligne commence par '#' + un nom d'événement
        if not comment_value.startswith("#"):
            return None

        # Regex: #eventtype [date] [#p place] [#s source]
        pattern = _re.compile(
            r"^#([A-Za-z][A-Za-z0-9_-]*)"  # groupe 1: type (tags #strng inclus)
            r"(?:\s+([^#]+?))?"  # groupe 2: date (optionnelle, avant #p ou #s)
            r"(?:\s+#p\s+([^#]+?))?"  # groupe 3: lieu (optionnel)
            r"(?:\s+#s\s+(.+?))?$",  # groupe 4: source (optionnelle)
            _re.IGNORECASE,
        )
        m = pattern.match(comment_value.strip())
        if not m:
            return None

        raw_tag = m.group(1)
        raw_type = raw_tag.lower()
        date_str = (m.group(2) or "").strip()
        place_str = (m.group(3) or "").strip()
        source_str = (m.group(4) or "").strip()

        # Mapper le type vers EventType
        if raw_type in _PEVT_TAG_ALIASES:
            # Alias GEDCOM : type canonique, tag d'origine conservé
            evt_type = _PEVT_TAG_ALIASES[raw_type]
            type_raw = raw_type
        else:
            try:
                evt_type = EventType(raw_type)
                type_raw = None
            except ValueError:
                evt_type = EventType.OTHER
                type_raw = raw_tag  # tag personnalisé (#strng) : casse d'origine

        # Parser la date
        evt_date = Date.parse_with_fallback(date_str) if date_str else None

        return PersonalEvent(
            event_type=evt_type,
            event_type_raw=type_raw,
            date=evt_date,
            place=place_str if place_str else None,
            source=source_str if source_str else None,
            person_id=person_id,
        )

    def _parse_place_value(
        self, tokens: List[Token], start_index: int
    ) -> Tuple[Optional[str], int]:
        """Parse une valeur de lieu (peut contenir plusieurs tokens séparés par virgules, etc.)

        Args:
            tokens: Liste des tokens
            start_index: Index de départ pour le parsing

        Returns:
            Tuple (valeur_du_lieu, nouvel_index)
        """
        place_parts = []
        i = start_index

        # Continuer à parser jusqu'à trouver un token spécial
        while i < len(tokens):
            token = tokens[i]

            # Tokens qui indiquent la fin du lieu
            if token.type in [
                TokenType.S,  # Source
                TokenType.WIT,  # Témoin
                TokenType.NOTE,  # Note
                TokenType.BIRT,  # Nouveau type d'événement
                TokenType.DEAT,
                TokenType.BAPT,
                TokenType.END_PEVT,  # Fin du bloc
                TokenType.NEWLINE,  # Nouvelle ligne
            ]:
                break

            # Tous les tokens font partie du lieu (identifiants, strings, virgules, etc.)
            place_parts.append(token.value)
            i += 1

        if place_parts:
            # Joindre les parties en préservant les espaces et caractères spéciaux
            place_value = "".join(place_parts)
            return place_value, i

        return None, start_index

    def _parse_short_place(
        self, tokens: List[Token], start_index: int
    ) -> Tuple[Optional[str], int]:
        """Lieu d'un champ de ligne de personne : un seul lieu, crochets compris."""
        fin = place_run_end(tokens, start_index)
        if fin == start_index:
            return None, start_index
        return _join_tokens_text(tokens[start_index:fin]), fin

    def _parse_short_source(
        self, tokens: List[Token], start_index: int
    ) -> Tuple[Optional[str], int]:
        """Source d'un champ de ligne de personne (``#bs``…) : un seul mot."""
        if start_index < len(tokens) and tokens[start_index].type in (
            TokenType.IDENTIFIER,
            TokenType.STRING,
        ):
            fin = mot_end(tokens, start_index)
            return _join_tokens_text(tokens[start_index:fin]), fin
        return None, start_index

    def _parse_source_value(
        self, tokens: List[Token], start_index: int
    ) -> Tuple[Optional[str], int]:
        """Parse une valeur de source (peut contenir plusieurs tokens)

        Args:
            tokens: Liste des tokens
            start_index: Index de départ pour le parsing (après #s)

        Returns:
            Tuple (valeur_de_la_source, nouvel_index)
        """
        source_tokens: List[Token] = []
        i = start_index

        # Continuer à parser jusqu'à trouver un token spécial
        while i < len(tokens):
            token = tokens[i]

            # Tokens qui indiquent la fin de la source
            if token.type in [
                TokenType.WIT,  # Témoin
                TokenType.NOTE,  # Note
                TokenType.BIRT,  # Nouveau type d'événement
                TokenType.DEAT,
                TokenType.BAPT,
                TokenType.END_PEVT,  # Fin du bloc
                TokenType.NEWLINE,  # Nouvelle ligne
            ]:
                break

            # Tous les autres tokens font partie de la source
            source_tokens.append(token)
            i += 1

        if source_tokens:
            return _join_tokens_text(source_tokens), i

        return None, start_index

    def _parse_title_bracket(
        self, tokens: List[Token], start_index: int
    ) -> Tuple[Optional[Title], int]:
        """Parse [TitleName:Type:Place:StartDate:EndDate:Nth] from BRACKET_OPEN.

        Args:
            tokens: Liste des tokens
            start_index: Index où commence BRACKET_OPEN

        Returns:
            Tuple (Title object ou None, nouvel_index)
        """
        i = start_index
        if i >= len(tokens) or tokens[i].type != TokenType.BRACKET_OPEN:
            return None, i
        i += 1  # consume BRACKET_OPEN

        fields: List[List[str]] = [[]]
        while i < len(tokens) and tokens[i].type != TokenType.BRACKET_CLOSE:
            tok = tokens[i]
            if tok.type == TokenType.COLON:
                fields.append([])
            else:
                fields[-1].append(tok.value)
            i += 1

        if i < len(tokens) and tokens[i].type == TokenType.BRACKET_CLOSE:
            i += 1  # consume BRACKET_CLOSE

        def field_str(idx: int) -> str:
            if idx < len(fields):
                return " ".join(fields[idx]).replace("_", " ")
            return ""

        title_name = field_str(0).strip()
        title_type = field_str(1).strip()
        place = field_str(2).strip()
        start_raw = field_str(3).strip()
        end_raw = field_str(4).strip()
        nth_raw = field_str(5).strip()

        start_date = Date.parse_with_fallback(start_raw) if start_raw else None
        end_date = Date.parse_with_fallback(end_raw) if end_raw else None
        nth = int(nth_raw) if nth_raw.isdigit() else 1

        title = Title(
            name=title_name,
            title_type=title_type,
            place=place,
            start_date=start_date,
            end_date=end_date,
            number=nth,
            is_main=(title_name == "*"),
        )
        return title, i

    def _parse_person_events_block(
        self, node: SyntaxNode, persons: dict, genealogy: Genealogy
    ) -> None:
        """Parse un bloc événements personnels et met à jour la personne correspondante"""  # noqa: E501
        tokens = node.tokens

        # Extraire le nom de la personne
        if (
            len(tokens) >= 3
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.IDENTIFIER
        ):
            last_name = tokens[1].value
            first_name = tokens[2].value

            person_id = f"{last_name}_{first_name}_0"

            # Créer la personne si elle n'existe pas
            if person_id not in persons:
                person = Person(
                    last_name=last_name,
                    first_name=first_name,
                    gender=Gender.UNKNOWN,  # Sera déterminé plus tard
                )
                persons[person_id] = person
                genealogy.add_or_update_person(person)

            person = persons[person_id]
            _mark_person_defined(person, *_node_line_span(node))
            events_before = len(person.events)

            # Parser les événements
            i = 3  # Passer pevt, nom, prénom
            # Garder une référence au dernier événement construit pour y rattacher les témoins  # noqa: E501
            last_event = None
            note_tail: Optional[Tuple[Any, int]] = (
                None  # (porteur, dernière ligne de note)
            )
            while i < len(tokens):
                token = tokens[i]

                # Événements avec dates
                if token.type == TokenType.BIRT:
                    i += 1
                    from ..event import EventType, PersonalEvent

                    # Date de naissance (optionnelle)
                    birth_date = None
                    if i < len(tokens) and tokens[i].type == TokenType.DATE:
                        birth_date = Date.parse_with_fallback(tokens[i].value)
                        person.birth_date = birth_date
                        i += 1
                    else:
                        # Pas de date -> date inconnue
                        person.birth_date = Date(is_unknown=True)
                        birth_date = Date(is_unknown=True)

                    # Lieu de naissance (optionnel)
                    birth_place = None
                    if i < len(tokens) and tokens[i].type == TokenType.P:
                        i += 1
                        birth_place, i = self._parse_place_value(tokens, i)
                        if birth_place:
                            person.birth_place = birth_place

                    # Source (optionnelle, après le lieu ou la date)
                    birth_source = None
                    if i < len(tokens) and tokens[i].type == TokenType.S:
                        i += 1
                        birth_source, i = self._parse_source_value(tokens, i)

                    # Créer l'événement de naissance et l'ajouter
                    birth_event = PersonalEvent(
                        event_type=EventType.BIRTH,
                        date=birth_date,
                        place=birth_place,
                        source=birth_source,
                        person_id=person.unique_id,
                    )
                    person.add_event(birth_event)
                    last_event = birth_event
                    birth_event.start_line = token.line_number

                elif token.type == TokenType.DEAT:
                    i += 1
                    from ..event import EventType, PersonalEvent

                    # Date de décès (optionnelle)
                    death_date = None
                    if i < len(tokens) and tokens[i].type == TokenType.DATE:
                        death_date = Date.parse_with_fallback(tokens[i].value)
                        person.death_date = death_date
                        i += 1
                    else:
                        # Pas de date -> date inconnue
                        person.death_date = Date(is_unknown=True)
                        death_date = Date(is_unknown=True)

                    # Lieu de décès (optionnel)
                    death_place = None
                    if i < len(tokens) and tokens[i].type == TokenType.P:
                        i += 1
                        death_place, i = self._parse_place_value(tokens, i)
                        if death_place:
                            person.death_place = death_place

                    # Source (optionnelle, après le lieu ou la date)
                    death_source = None
                    if i < len(tokens) and tokens[i].type == TokenType.S:
                        i += 1
                        death_source, i = self._parse_source_value(tokens, i)

                    # Créer l'événement de décès et l'ajouter
                    death_event = PersonalEvent(
                        event_type=EventType.DEATH,
                        date=death_date,
                        place=death_place,
                        source=death_source,
                        person_id=person.unique_id,
                    )
                    person.add_event(death_event)
                    last_event = death_event
                    death_event.start_line = token.line_number

                elif token.type == TokenType.BAPT:
                    i += 1
                    from ..event import EventType, PersonalEvent

                    # Date de baptême (optionnelle)
                    baptism_date = None
                    if i < len(tokens) and tokens[i].type == TokenType.DATE:
                        try:
                            baptism_date = Date.parse_with_fallback(tokens[i].value)
                        except Exception:
                            # En cas d'erreur, ignorer silencieusement
                            pass
                        i += 1

                    # Lieu de baptême (optionnel)
                    baptism_place = None
                    if i < len(tokens) and tokens[i].type == TokenType.P:
                        i += 1
                        baptism_place, i = self._parse_place_value(tokens, i)

                    # Source (optionnelle, après le lieu ou la date)
                    baptism_source = None
                    if i < len(tokens) and tokens[i].type == TokenType.S:
                        i += 1
                        baptism_source, i = self._parse_source_value(tokens, i)

                    # Créer l'événement de baptême et l'ajouter
                    if baptism_date is not None or baptism_place is not None:
                        baptism_event = PersonalEvent(
                            event_type=EventType.BAPTISM,
                            date=baptism_date,
                            place=baptism_place,
                            source=baptism_source,
                            person_id=person.unique_id,
                        )
                        person.add_event(baptism_event)
                        last_event = baptism_event
                        baptism_event.start_line = token.line_number

                elif token.type == TokenType.NOTE:
                    i += 1
                    # Contenu de la note
                    note_content: List[str] = []
                    note_agg = 0
                    note_debut = i
                    while i < len(tokens) and tokens[i].type not in [
                        TokenType.NEWLINE,
                        TokenType.END_PEVT,
                        TokenType.BIRT,
                        TokenType.DEAT,
                        TokenType.BAPT,
                        TokenType.NOTE,
                        TokenType.WIT,
                    ]:
                        note_agg, stop = _bounded_append_text_fragment(
                            note_content,
                            note_agg,
                            tokens[i].value,
                            inter_fragment_sep_len=1,
                            max_fragments=_TEXT_AGGREGATE_MAX_FRAGMENTS,
                            max_aggregate_chars=_TEXT_AGGREGATE_MAX_CHARS,
                            log_context="Note pevt",
                        )
                        i += 1
                        if stop:
                            break
                    if note_content:
                        note_text = texte_libre(tokens[note_debut:i], len(note_content))
                        # Associer la note à l'événement courant si disponible, sinon à la personne
                        if last_event is not None:
                            last_event.add_note(note_text)
                        else:
                            person.add_note(note_text)
                        note_tail = (last_event or person, tokens[i - 1].line_number)

                elif token.type == TokenType.WIT:
                    # Parser les témoins avec informations complètes et les rattacher à l'événement courant  # noqa: E501
                    next_i, witness_id, witness_type, witness_kind = (
                        self._parse_witness_person(tokens, i, persons, genealogy)
                    )
                    if witness_id and last_event is not None:
                        last_event.add_witness(witness_id, witness_type, witness_kind)
                    i = next_i

                elif token.type == TokenType.COMMENT:
                    # Lignes de type "#eventtype [date] [#p place] [#s source]"
                    # dans un bloc pevt — parser via regex car tokenisées en COMMENT
                    evt = self._parse_pevt_comment_line(token.value, person.unique_id)
                    if evt is not None:
                        evt.start_line = token.line_number
                        person.add_event(evt)
                        last_event = evt
                    i += 1

                elif token.type in _PEVT_DEDICATED_TOKENS:
                    # #occu / #buri / #crem : tokens dédiés du lexer, reconstitués
                    # en ligne puis traités comme les autres événements
                    event_line = token.line_number
                    line_text, i = _tokens_line_text(tokens, i)
                    evt = self._parse_pevt_comment_line(line_text, person.unique_id)
                    if evt is not None:
                        evt.start_line = event_line
                        person.add_event(evt)
                        last_event = evt

                elif _is_line_start_note(tokens, i):
                    # "note ..." sans '#' : lexé en IDENTIFIER, rattaché à l'événement
                    line_text, i = _tokens_line_text(tokens, i)
                    _, _, note_text = line_text.partition(" ")
                    note_text = note_text.strip()
                    if note_text:
                        if last_event is not None:
                            last_event.add_note(note_text)
                        else:
                            person.add_note(note_text)
                        note_tail = (last_event or person, token.line_number)

                elif token.type not in (
                    TokenType.NEWLINE,
                    TokenType.WHITESPACE,
                    TokenType.END_PEVT,
                    TokenType.EOF,
                ) and (i == 0 or tokens[i - 1].type == TokenType.NEWLINE):
                    # Texte nu (R13) : suite de la note précédente si elle occupe la
                    # ligne d'avant, sinon note de l'événement courant
                    line_no = token.line_number
                    line_text, i = _tokens_line_text(tokens, i)
                    holder = last_event or person
                    if (
                        token.type == TokenType.WNOTE
                        and last_event is not None
                        and _attach_wnote(last_event.witnesses, line_text)
                    ):
                        continue
                    if note_tail is not None and note_tail[1] == line_no - 1:
                        holder = note_tail[0]
                        holder.notes[-1] += "\n" + line_text
                    else:
                        holder.add_note(line_text)
                    note_tail = (holder, line_no)

                else:
                    i += 1

            _assign_event_end_lines(person.events[events_before:], tokens)

    def _parse_fevt_spouse_header(
        self,
        tokens: List[Token],
        start_index: int,
        persons: Dict[str, Person],
        genealogy: Genealogy,
    ) -> Tuple[Optional[str], Optional[str], int]:
        """Lit l'en-tête époux après ``fevt``.

        S'arrête au premier jeton d'événement ou à la fin du bloc.

        Returns:
            Tuple ``(husband_id, wife_id, index_du_premier_token_non_entête)``.
        """
        i = start_index
        current = "husband"
        h_name: Optional[str] = None
        h_fn: Optional[str] = None
        h_occ: Optional[int] = None
        w_name: Optional[str] = None
        w_fn: Optional[str] = None
        w_occ: Optional[int] = None

        while i < len(tokens):
            tok = tokens[i]
            if tok.type in (TokenType.END_FEVT, TokenType.NEWLINE):
                break
            if tok.type in (
                TokenType.MARR,
                TokenType.DIV_EVENT,
                TokenType.SEP_EVENT,
                TokenType.ENGA,
                TokenType.WIT,
                TokenType.SRC,
                TokenType.COMM,
                TokenType.NOTE,
            ):
                break
            if tok.type == TokenType.PLUS:
                current = "wife"
                i += 1
                continue
            if tok.type == TokenType.NUMBER:
                occ_str = tok.value.lstrip(".")
                try:
                    occ_val = int(occ_str)
                except ValueError:
                    occ_val = 0
                if current == "husband" and h_fn is not None:
                    h_occ = occ_val
                elif current == "wife" and w_fn is not None:
                    w_occ = occ_val
                i += 1
                continue
            if tok.type == TokenType.IDENTIFIER:
                if current == "husband":
                    if h_name is None:
                        h_name = tok.value
                    elif h_fn is None:
                        h_fn = tok.value
                    elif w_name is None:
                        current = "wife"
                        w_name = tok.value
                    else:
                        break
                else:
                    if w_name is None:
                        w_name = tok.value
                    elif w_fn is None:
                        w_fn = tok.value
                    else:
                        break
            i += 1

        husband_id: Optional[str] = None
        wife_id: Optional[str] = None
        if h_name and h_fn:
            husband_id = self._get_or_create_person(
                h_name, h_fn, h_occ, persons, genealogy, Gender.MALE
            )
        if w_name and w_fn:
            wife_id = self._get_or_create_person(
                w_name, w_fn, w_occ, persons, genealogy, Gender.FEMALE
            )
        return husband_id, wife_id, i

    def _find_family_for_fevt_spouses(
        self,
        families: Dict[str, Family],
        husband_id: Optional[str],
        wife_id: Optional[str],
    ) -> Optional[Family]:
        """Retrouve la famille dont les époux correspondent au bloc ``fevt``."""
        if husband_id and wife_id:
            for fam in families.values():
                pair = {fam.husband_id, fam.wife_id}
                if husband_id in pair and wife_id in pair:
                    return fam
            return None
        sole = husband_id or wife_id
        if sole is None:
            return None
        candidates = [
            fam for fam in families.values() if sole in (fam.husband_id, fam.wife_id)
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _consume_family_event_optional_fields(
        self, tokens: List[Token], start_index: int, event: FamilyEvent
    ) -> int:
        """Consomme date, lieu ``#p`` et source ``#s`` après le type d'événement."""
        i = start_index
        while i < len(tokens):
            tok = tokens[i]
            if tok.type == TokenType.DATE:
                event.date = Date.parse_with_fallback(tok.value)
                i += 1
                continue
            if tok.type == TokenType.P:
                i += 1
                if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                    event.place = tokens[i].value
                    i += 1
                continue
            if tok.type == TokenType.S:
                i += 1
                source, i = self._parse_source_value(tokens, i)
                if source is not None:
                    event.source = source
                continue
            break
        return i

    def _family_event_from_token(self, token_type: TokenType) -> FamilyEvent:
        """Construit un ``FamilyEvent`` à partir du jeton de type d'événement."""
        mapping: Dict[TokenType, FamilyEventType] = {
            TokenType.MARR: FamilyEventType.MARRIAGE,
            TokenType.DIV_EVENT: FamilyEventType.DIVORCE,
            TokenType.SEP_EVENT: FamilyEventType.SEPARATION,
            TokenType.ENGA: FamilyEventType.ENGAGEMENT,
        }
        fet = mapping[token_type]
        evt_type = {
            FamilyEventType.MARRIAGE: EventType.MARRIAGE,
            FamilyEventType.DIVORCE: EventType.DIVORCE,
            FamilyEventType.SEPARATION: EventType.SEPARATION,
            FamilyEventType.ENGAGEMENT: EventType.ENGAGEMENT,
        }[fet]
        return FamilyEvent(event_type=evt_type, family_event_type=fet)

    def _family_event_from_comment(self, comment_value: str) -> Optional[FamilyEvent]:
        """Événement familial d'une ligne ``#tag [date] [#p lieu] [#s source]``.

        Le lexeur rend en COMMENT toute ligne ``#tag`` qu'il ne connaît pas
        (``#marc``, ``#resi``, tag libre…). Un tag familial standard garde son
        type ; tout autre tag devient ``OTHER`` avec la casse d'origine dans
        ``event_type_raw``. None si la ligne n'est pas de la forme ``#tag``.
        """
        import re as _re

        m = _re.match(
            r"^#([A-Za-z][A-Za-z0-9_-]*)"
            r"(?:\s+([^#]+?))?"
            r"(?:\s+#p\s+([^#]+?))?"
            r"(?:\s+#s\s+(.+?))?$",
            comment_value.strip(),
        )
        if not m:
            return None
        raw_tag = m.group(1)
        try:
            fet = FamilyEventType(raw_tag.lower())
            type_raw = None
        except ValueError:
            fet = FamilyEventType.OTHER
            type_raw = raw_tag
        try:
            evt_type = EventType(fet.value)
        except ValueError:
            evt_type = EventType.OTHER
        date_str = (m.group(2) or "").strip()
        evt = FamilyEvent(
            event_type=evt_type,
            family_event_type=fet,
            event_type_raw=type_raw,
            date=Date.parse_with_fallback(date_str) if date_str else None,
            place=(m.group(3) or "").strip() or None,
            source=(m.group(4) or "").strip() or None,
        )
        return evt

    def _parse_family_events_block(
        self,
        node: SyntaxNode,
        persons: Dict[str, Person],
        families: Dict[str, Family],
        genealogy: Genealogy,
        current_family: Optional[Family],
    ) -> None:
        """Parse ``fevt`` et rattache les événements à ``Family.events``.

        Famille cible : correspondance par époux du bloc ; sans correspondance mais
        avec des identifiants d'époux, aucune famille n'est choisie (avertissement).
        Sans ligne d'époux, repli sur ``current_family`` (dernier bloc ``fam``).

        Plafonds par bloc (entrées volumineuses) : voir
        ``_FEVT_MAX_EVENTS_PER_BLOCK`` et ``_FEVT_MAX_WITNESSES_PER_BLOCK``.
        """
        tokens = node.tokens
        witness_persons: Dict[str, Person] = {}

        husband_id: Optional[str]
        wife_id: Optional[str]
        husband_id, wife_id, i = self._parse_fevt_spouse_header(
            tokens, 1, persons, genealogy
        )

        resolved = self._find_family_for_fevt_spouses(families, husband_id, wife_id)
        line_number = tokens[0].line_number if tokens else None
        target_family: Optional[Family]
        if resolved is not None:
            target_family = resolved
        elif husband_id is not None or wife_id is not None:
            _hint_parts: List[str] = []
            if husband_id is not None:
                _hint_parts.append(f"père={husband_id}")
            if wife_id is not None:
                _hint_parts.append(f"mère={wife_id}")
            spouse_hint = ", ".join(_hint_parts)
            msg = (
                "Bloc fevt: aucune famille ne correspond aux époux indiqués ; "
                "événements non rattachés (évite une mauvaise famille cible)."
            )
            if spouse_hint:
                msg = f"{msg} Époux: {spouse_hint}."
            self.error_collector.add_error(
                ParseWarning(
                    msg,
                    line_number=line_number,
                    context="fevt",
                )
            )
            target_family = None
        else:
            target_family = current_family

        parsed_events: List[FamilyEvent] = []
        current_event: Optional[FamilyEvent] = None
        fevt_event_count = 0
        fevt_witness_count = 0
        fevt_events_truncated = False
        fevt_witnesses_truncated = False

        while i < len(tokens):
            token = tokens[i]

            if token.type == TokenType.END_FEVT:
                break

            if token.type == TokenType.WIT:
                if fevt_witness_count >= _FEVT_MAX_WITNESSES_PER_BLOCK:
                    if not fevt_witnesses_truncated:
                        self.error_collector.add_error(
                            ParseWarning(
                                f"Bloc fevt: limite de {_FEVT_MAX_WITNESSES_PER_BLOCK} "
                                "témoins atteinte ; témoins supplémentaires ignorés "
                                "(protection ressource).",
                                line_number=token.line_number,
                                context="fevt",
                            )
                        )
                        fevt_witnesses_truncated = True
                    i = self._skip_fevt_witness_person(tokens, i)
                    continue
                fevt_witness_count += 1
                next_i, witness_id, witness_type, witness_kind = (
                    self._parse_witness_person(tokens, i, witness_persons, genealogy)
                )
                if witness_id and current_event is not None:
                    current_event.add_witness(witness_id, witness_type, witness_kind)
                i = next_i
                continue

            if token.type in (
                TokenType.MARR,
                TokenType.DIV_EVENT,
                TokenType.SEP_EVENT,
                TokenType.ENGA,
            ):
                if fevt_event_count >= _FEVT_MAX_EVENTS_PER_BLOCK:
                    if not fevt_events_truncated:
                        self.error_collector.add_error(
                            ParseWarning(
                                f"Bloc fevt: limite de {_FEVT_MAX_EVENTS_PER_BLOCK} "
                                "événements atteinte ; suite du bloc ignorée "
                                "(protection ressource).",
                                line_number=token.line_number,
                                context="fevt",
                            )
                        )
                        fevt_events_truncated = True
                    discard_evt = self._family_event_from_token(token.type)
                    i += 1
                    i = self._consume_family_event_optional_fields(
                        tokens, i, discard_evt
                    )
                    continue
                fevt_event_count += 1
                current_event = self._family_event_from_token(token.type)
                current_event.start_line = token.line_number
                parsed_events.append(current_event)
                i += 1
                i = self._consume_family_event_optional_fields(tokens, i, current_event)
                continue

            if token.type == TokenType.COMMENT and token.value.startswith("#"):
                comment_evt = self._family_event_from_comment(token.value)
                i += 1
                if comment_evt is None:
                    continue
                if fevt_event_count >= _FEVT_MAX_EVENTS_PER_BLOCK:
                    fevt_events_truncated = True
                    continue
                fevt_event_count += 1
                comment_evt.start_line = token.line_number
                current_event = comment_evt
                parsed_events.append(comment_evt)
                continue

            if token.type == TokenType.SRC:
                i += 1
                if (
                    current_event is not None
                    and i < len(tokens)
                    and tokens[i].type in (TokenType.IDENTIFIER, TokenType.STRING)
                ):
                    current_event.source = tokens[i].value
                    i += 1
                continue

            if token.type == TokenType.COMM:
                i += 1
                if (
                    current_event is not None
                    and i < len(tokens)
                    and tokens[i].type in (TokenType.IDENTIFIER, TokenType.STRING)
                ):
                    current_event.add_note(tokens[i].value)
                    i += 1
                continue

            if _is_line_start_note(tokens, i):
                # "note ..." sans '#' : lexé en IDENTIFIER, rattaché à l'événement courant
                line_text, i = _tokens_line_text(tokens, i)
                _, _, note_text = line_text.partition(" ")
                if note_text.strip() and current_event is not None:
                    current_event.add_note(note_text.strip())
                continue

            if token.type == TokenType.NOTE:
                i += 1
                note_content: List[str] = []
                note_agg = 0
                note_debut = i
                while i < len(tokens) and tokens[i].type not in [
                    TokenType.NEWLINE,
                    TokenType.END_FEVT,
                    TokenType.MARR,
                    TokenType.DIV_EVENT,
                    TokenType.SEP_EVENT,
                    TokenType.ENGA,
                    TokenType.WIT,
                ]:
                    note_agg, stop = _bounded_append_text_fragment(
                        note_content,
                        note_agg,
                        tokens[i].value,
                        inter_fragment_sep_len=1,
                        max_fragments=_TEXT_AGGREGATE_MAX_FRAGMENTS,
                        max_aggregate_chars=_TEXT_AGGREGATE_MAX_CHARS,
                        log_context="Note fevt",
                    )
                    i += 1
                    if stop:
                        break
                if note_content and current_event is not None:
                    current_event.add_note(
                        texte_libre(tokens[note_debut:i], len(note_content))
                    )
                continue

            if token.type in (
                TokenType.WNOTE,
                TokenType.IDENTIFIER,
                TokenType.STRING,
                TokenType.NUMBER,
            ) and (i == 0 or tokens[i - 1].type == TokenType.NEWLINE):
                # Texte nu ou ``wnote`` (R13) : ligne gardée telle quelle
                est_wnote = token.type == TokenType.WNOTE
                line_text, i = _tokens_line_text(tokens, i)
                if current_event is not None and not (
                    est_wnote and _attach_wnote(current_event.witnesses, line_text)
                ):
                    current_event.add_note(line_text)
                continue

            i += 1

        _assign_event_end_lines(parsed_events, tokens)

        for pid, person in witness_persons.items():
            if pid not in persons:
                persons[pid] = person

        if target_family is not None and parsed_events:
            for fev in parsed_events:
                fev.family_id = target_family.family_id
                target_family.add_event(fev)

        witnesses = []
        if witness_persons:
            for person in witness_persons.values():
                witness_dict = {
                    "person_id": person.unique_id,
                    "type": "male" if person.gender == Gender.MALE else "female",
                    "name": f"{person.last_name} {person.first_name}",
                    "person": person,
                }
                witnesses.append(witness_dict)
        node.metadata["witnesses"] = witnesses

    def get_tokens(self) -> List[Token]:
        """Retourne la liste des tokens du dernier parsing"""
        return self.tokens

    def get_syntax_nodes(self) -> List[SyntaxNode]:
        """Retourne la liste des nœuds syntaxiques du dernier parsing"""
        return self.syntax_nodes

    def _parse_relations_block(
        self, node: SyntaxNode, persons: dict, genealogy: Genealogy
    ) -> None:
        """Parse un bloc relations et crée les Person référencées"""
        tokens = node.tokens

        # Extraire le nom de la personne concernée
        if (
            len(tokens) >= 3
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.IDENTIFIER
        ):
            subject_occurrence = None
            if len(tokens) > 3 and tokens[3].type == TokenType.NUMBER:
                subject_occurrence = self._occurrence_from_token(tokens[3])

            person_id = self._get_or_create_person(
                tokens[1].value,
                tokens[2].value,
                subject_occurrence,
                persons,
                genealogy,
            )

            # Parser les relations dans les enfants du nœud
            for child_node in node.children:
                if child_node.tokens and child_node.tokens[0].type == TokenType.DASH:
                    relation = self._parse_relation_line(child_node, persons, genealogy)
                    if relation:
                        persons[person_id].add_relation_link(relation)

    @staticmethod
    def _occurrence_from_token(token: Token) -> int:
        """Numéro d'occurrence d'un jeton ``.N`` (0 si illisible)"""
        try:
            return int(token.value.lstrip("."))
        except ValueError:
            return 0

    def _parse_relation_line(
        self, child_node: SyntaxNode, persons: dict, genealogy: Genealogy
    ) -> Optional[Relation]:
        """Parse une ligne de relation et crée la Person référencée"""
        tokens = child_node.tokens

        if len(tokens) < 4:  # Au minimum: -, type, :, nom
            return None

        # Type de relation (adop, reco, cand, godp, fost)
        relation_type: Optional[RelationType] = None
        parent_role: Optional[ParentRole] = None
        person_tokens: List[str] = []
        occurrence: Optional[int] = None

        i = 1  # Passer le tiret

        if i < len(tokens) and tokens[i].type in [
            TokenType.ADOP,
            TokenType.RECO,
            TokenType.CAND,
            TokenType.GODP,
            TokenType.FOST,
        ]:
            relation_type = RelationType(tokens[i].value.lstrip("#"))
            i += 1

        # Côté du parent (fath, moth) - optionnel
        if i < len(tokens) and tokens[i].type in [TokenType.FATH, TokenType.MOTH]:
            parent_role = ParentRole(tokens[i].value)
            i += 1

        # Passer les deux points
        if i < len(tokens) and tokens[i].type == TokenType.COLON:
            i += 1

        # Collecter les tokens de la personne
        while i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
            person_tokens.append(tokens[i].value)
            i += 1
        if i < len(tokens) and tokens[i].type == TokenType.NUMBER:
            occurrence = self._occurrence_from_token(tokens[i])

        if relation_type is None or len(person_tokens) < 2:
            return None

        target_id = self._get_or_create_person(
            person_tokens[0], person_tokens[1], occurrence, persons, genealogy
        )
        ligne = tokens[0].line_number
        return Relation(relation_type, parent_role, target_id, ligne, ligne)

    @staticmethod
    def _witness_kind_at(tokens: List[Token], index: int) -> Optional[WitnessKind]:
        """Rôle de témoin du jeton à ``index`` (``#godp``, ``#offi``), sinon None."""
        if index >= len(tokens):
            return None
        if tokens[index].type == TokenType.GODP:
            return WitnessKind.GODPARENT
        if tokens[index].type == TokenType.OFFI:
            return WitnessKind.OFFICER
        return None

    def _skip_fevt_witness_person(self, tokens: List[Token], start_index: int) -> int:
        """Avance après un jeton ``wit`` sans créer de personne témoin.

        Utilisé lorsque le plafond de témoins par bloc ``fevt`` est atteint, pour
        rester aligné sur ``_parse_witness_person`` sans alimenter la généalogie.

        Args:
            tokens: Liste des tokens du bloc.
            start_index: Position du ``wit``.

        Returns:
            Index du prochain jeton après la séquence témoin.
        """
        i = start_index
        if i >= len(tokens) or tokens[i].type != TokenType.WIT:
            return min(start_index + 1, len(tokens))
        i += 1
        if i < len(tokens) and tokens[i].type in (TokenType.H, TokenType.F):
            i += 1
        if i < len(tokens) and tokens[i].type == TokenType.COLON:
            i += 1
        if self._witness_kind_at(tokens, i) is not None:
            i += 1
        if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
            i += 1
        if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
            i += 1
        if i < len(tokens) and tokens[i].type == TokenType.NUMBER:
            i += 1
        dummy = Person(
            last_name="_fevt_skip",
            first_name="_",
            gender=Gender.UNKNOWN,
            occurrence_number=-1,
        )
        return self._parse_inline_personal_info(tokens, i, dummy)

    def _parse_witness_person(
        self, tokens: List[Token], start_index: int, persons: dict, genealogy: Genealogy
    ) -> Tuple[int, Optional[str], Optional[str], Optional[WitnessKind]]:
        """Parse un témoin avec toutes ses informations personnelles

        Format: wit [m|f]: [#godp|#offi] LastName FirstName [dates] [#bp place] ...

        Args:
            tokens: Liste des tokens
            start_index: Index de début du témoin
            persons: Dictionnaire des personnes existantes
            genealogy: Objet Genealogy

        Returns:
            Tuple (index_suivant, witness_id, witness_type, witness_kind)
        """
        i = start_index

        # Passer le token wit
        if i >= len(tokens) or tokens[i].type != TokenType.WIT:
            return i + 1, None, None, None
        i += 1

        # Type de témoin (m ou f) - optionnel
        witness_gender = Gender.UNKNOWN
        witness_type: Optional[str] = None
        if i < len(tokens) and tokens[i].type in [TokenType.H, TokenType.F]:
            witness_gender = (
                Gender.MALE if tokens[i].type == TokenType.H else Gender.FEMALE
            )
            witness_type = "m" if tokens[i].type == TokenType.H else "f"
            i += 1

        # Passer les deux points
        if i < len(tokens) and tokens[i].type == TokenType.COLON:
            i += 1

        # Rôle explicite (#godp / #offi) entre les deux points et le nom
        witness_kind = self._witness_kind_at(tokens, i)
        if witness_kind is not None:
            i += 1

        # Extraire nom et prénom
        last_name = None
        first_name = None
        occurrence_num = None

        if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
            # un mot peut être découpé par le lexeur (``A/B``) : on le recolle
            fin = mot_end(tokens, i)
            if fin - 1 > i and tokens[fin - 1].type == TokenType.NUMBER:
                fin -= 1  # ``.1`` collé = numéro d'occurrence, pas le nom
            last_name = _join_tokens_text(tokens[i:fin])
            i = fin

        if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
            fin = mot_end(tokens, i)
            if fin - 1 > i and tokens[fin - 1].type == TokenType.NUMBER:
                fin -= 1  # ``.1`` collé = numéro d'occurrence, pas le nom
            first_name = _join_tokens_text(tokens[i:fin])
            i = fin

        # Numéro d'occurrence (après le prénom)
        if i < len(tokens) and tokens[i].type == TokenType.NUMBER:
            occurrence_str = tokens[i].value.lstrip(".")
            try:
                occurrence_num = int(occurrence_str)
            except ValueError:
                occurrence_num = 0
            i += 1

        if not last_name or not first_name:
            return i, None, None, None

        # Utiliser la nouvelle méthode de déduplication
        witness_id = self._get_or_create_person(
            last_name, first_name, occurrence_num, persons, genealogy, witness_gender
        )

        # Parser les informations personnelles supplémentaires
        i = self._parse_inline_personal_info(tokens, i, persons[witness_id])

        return i, witness_id, witness_type, witness_kind

    def _parse_inline_personal_info(
        self, tokens: List[Token], start_index: int, person: Person
    ) -> int:
        """Parse les informations personnelles inline (dates, lieux, occupation, etc.)

        Args:
            tokens: Liste des tokens
            start_index: Index de début
            person: Objet Person à mettre à jour

        Returns:
            Index suivant après les informations
        """
        i = start_index

        while i < len(tokens):
            token = tokens[i]

            # Date de naissance
            if token.type == TokenType.DATE:
                date_gw = Date.parse_with_fallback(token.value)
                if i > 0 and _is_bang(tokens[i - 1]):
                    person.baptism_date = date_gw
                elif person.birth_date is None:
                    person.birth_date = date_gw
                elif person.death_date is None:
                    person.death_date = date_gw
                i += 1

            # '!' devant la date de baptême : la date suivante l'indique
            elif _is_bang(token):
                i += 1

            # Lieu de naissance (#bp)
            elif token.type == TokenType.BP:
                i += 1
                value, i = self._parse_short_place(tokens, i)
                if value:
                    person.birth_place = value

            # Lieu de décès (#dp)
            elif token.type == TokenType.DP:
                i += 1
                value, i = self._parse_short_place(tokens, i)
                if value:
                    person.death_place = value

            # Occupation (#occu)
            elif token.type == TokenType.OCCU:
                i += 1
                occupation_parts: List[str] = []
                occ_agg = 0
                while i < len(tokens) and tokens[i].type in [
                    TokenType.IDENTIFIER,
                    TokenType.STRING,
                    TokenType.PAREN_OPEN,
                    TokenType.PAREN_CLOSE,
                    TokenType.UNKNOWN,
                ]:
                    # Remplacer les underscores par des espaces pour l'affichage
                    # Garder les virgules et apostrophes telles quelles
                    fragment = tokens[i].value.replace("_", " ")
                    occ_agg, stop = _bounded_append_text_fragment(
                        occupation_parts,
                        occ_agg,
                        fragment,
                        inter_fragment_sep_len=0,
                        max_fragments=_TEXT_AGGREGATE_MAX_FRAGMENTS,
                        max_aggregate_chars=_TEXT_AGGREGATE_MAX_CHARS,
                        log_context="Occupation inline",
                    )
                    i += 1
                    if stop:
                        break
                if occupation_parts:
                    person.occupation = "".join(occupation_parts)

            # Surnom (#nick)
            elif token.type == TokenType.NICK:
                i += 1
                if i < len(tokens) and tokens[i].type in (
                    TokenType.IDENTIFIER,
                    TokenType.STRING,
                ):
                    person.nickname = tokens[i].value.replace("_", " ")
                    i += 1

            # Alias de nom de famille (#salias)
            elif token.type == TokenType.SALIAS:
                i += 1
                if i < len(tokens) and tokens[i].type in (
                    TokenType.IDENTIFIER,
                    TokenType.STRING,
                ):
                    person.surname_alias = tokens[i].value
                    i += 1

            # Alias général (#alias)
            elif token.type == TokenType.ALIAS:
                i += 1
                if i < len(tokens) and tokens[i].type in (
                    TokenType.IDENTIFIER,
                    TokenType.STRING,
                ):
                    person.general_alias = tokens[i].value
                    i += 1

            # Chemin image (#image)
            elif token.type == TokenType.IMAGE:
                i += 1
                image_parts = []
                # Consume tokens until newline/eof/modifier
                while i < len(tokens) and tokens[i].type not in (
                    TokenType.NEWLINE,
                    TokenType.EOF,
                    TokenType.WIT,
                    TokenType.SRC,
                    TokenType.COMM,
                    TokenType.NOTE,
                ):
                    # Stop at known modifiers
                    if tokens[i].type in (
                        TokenType.NICK,
                        TokenType.SALIAS,
                        TokenType.ALIAS,
                        TokenType.BP,
                        TokenType.DP,
                        TokenType.OCCU,
                        TokenType.APUBL,
                        TokenType.APRIV,
                    ):
                        break
                    image_parts.append(tokens[i].value)
                    i += 1
                if image_parts:
                    person.image_path = "".join(image_parts)

            # Source naissance (#bs)
            elif token.type == TokenType.BS:
                i += 1
                value, i = self._parse_short_source(tokens, i)
                if value:
                    person.birth_source = value.replace("_", " ")

            # Source décès (#ds)
            elif token.type == TokenType.DS:
                i += 1
                value, i = self._parse_short_source(tokens, i)
                if value:
                    person.death_source = value.replace("_", " ")

            # Lieu baptême (#pp)
            elif token.type == TokenType.PP:
                i += 1
                value, i = self._parse_short_place(tokens, i)
                if value:
                    person.baptism_place = value.replace("_", " ")

            # Source baptême (#ps)
            elif token.type == TokenType.PS:
                i += 1
                value, i = self._parse_short_source(tokens, i)
                if value:
                    person.baptism_source = value.replace("_", " ")

            # Lieu inhumation (#rp)
            elif token.type == TokenType.RP:
                i += 1
                value, i = self._parse_short_place(tokens, i)
                if value:
                    person.burial_place = value.replace("_", " ")

            # Source inhumation (#rs)
            elif token.type == TokenType.RS:
                i += 1
                value, i = self._parse_short_source(tokens, i)
                if value:
                    person.burial_source = value.replace("_", " ")

            # Nom public (PublicName)
            elif token.type == TokenType.PAREN_OPEN:
                parts: List[str] = []
                i += 1
                while i < len(tokens) and tokens[i].type != TokenType.PAREN_CLOSE:
                    parts.append(tokens[i].value.replace("_", " "))
                    i += 1
                if i < len(tokens) and tokens[i].type == TokenType.PAREN_CLOSE:
                    i += 1
                if parts:
                    person.public_name = " ".join(parts)

            # Alias de prénom {FirstNameAlias}
            elif token.type == TokenType.BRACE_OPEN:
                parts = []
                i += 1
                while i < len(tokens) and tokens[i].type != TokenType.BRACE_CLOSE:
                    parts.append(tokens[i].value.replace("_", " "))
                    i += 1
                if i < len(tokens) and tokens[i].type == TokenType.BRACE_CLOSE:
                    i += 1
                if parts:
                    person.first_name_alias = " ".join(parts)

            # Titres [TitleName:Type:Place:StartDate:EndDate:Nth]
            elif token.type == TokenType.BRACKET_OPEN:
                title, i = self._parse_title_bracket(tokens, i)
                if title is not None:
                    person.add_title(title)

            # Accès privé (#apriv)
            elif token.type == TokenType.APRIV:
                person.access_level = AccessLevel.PRIVATE
                i += 1

            # Accès public (#apubl)
            elif token.type == TokenType.APUBL:
                person.access_level = AccessLevel.PUBLIC
                i += 1

            # Notes (#note)
            elif token.type == TokenType.NOTE:
                i += 1
                note_content: List[str] = []
                note_agg = 0
                note_debut = i
                while i < len(tokens) and tokens[i].type not in [
                    TokenType.NEWLINE,
                    TokenType.WIT,
                    TokenType.SRC,
                    TokenType.COMM,
                ]:
                    note_agg, stop = _bounded_append_text_fragment(
                        note_content,
                        note_agg,
                        tokens[i].value,
                        inter_fragment_sep_len=1,
                        max_fragments=_TEXT_AGGREGATE_MAX_FRAGMENTS,
                        max_aggregate_chars=_TEXT_AGGREGATE_MAX_CHARS,
                        log_context="Note inline",
                    )
                    i += 1
                    if stop:
                        break
                if note_content:
                    person.add_note(
                        texte_libre(tokens[note_debut:i], len(note_content))
                    )

            # Sources (#src)
            elif token.type == TokenType.SRC:
                i += 1
                if i < len(tokens) and tokens[i].type in [
                    TokenType.IDENTIFIER,
                    TokenType.STRING,
                ]:
                    # Par défaut, stocker en note pour compat; évitons de créer des personnes  # noqa: E501
                    source_value = tokens[i].value
                    person.add_note(f"Source: {source_value}")
                    i += 1

            # Commentaires (#comm)
            elif token.type == TokenType.COMM:
                i += 1
                if i < len(tokens) and tokens[i].type in [
                    TokenType.IDENTIFIER,
                    TokenType.STRING,
                ]:
                    person.add_note(f"Commentaire: {tokens[i].value}")
                    i += 1

            # Fin de ligne ou autre token non reconnu
            elif token.type in [
                TokenType.NEWLINE,
                TokenType.WIT,
                TokenType.SRC,
                TokenType.COMM,
            ]:
                break

            else:
                i += 1

        return i

    def _find_person_info_start(
        self, tokens: List[Token], last_name: str, first_name: str
    ) -> int:
        """Trouve l'index où commencent les informations personnelles d'une personne

        Args:
            tokens: Liste des tokens
            last_name: Nom de famille de la personne
            first_name: Prénom de la personne

        Returns:
            Index de début des informations personnelles, ou -1 si non trouvé
        """
        i = 0
        while i < len(tokens) - 1:
            # Chercher le nom de famille
            if (
                tokens[i].type == TokenType.IDENTIFIER
                and tokens[i].value == last_name
                and i + 1 < len(tokens)
                and tokens[i + 1].type == TokenType.IDENTIFIER
                and tokens[i + 1].value == first_name
            ):
                # Vérifier que c'est bien cette personne (pas un autre avec le même nom)
                # En regardant le contexte (pas après 'fam', pas avant '+')
                if i > 0 and tokens[i - 1].type == TokenType.FAM:
                    # C'est le mari, les infos commencent après le prénom
                    return i + 2
                elif i > 0 and tokens[i - 1].type == TokenType.PLUS:
                    # C'est la femme, les infos commencent après le prénom
                    return i + 2
                elif i > 0 and tokens[i - 1].type == TokenType.IDENTIFIER:
                    # C'est probablement un enfant, les infos commencent après le prénom
                    return i + 2
            i += 1

        return -1

    def _parse_database_notes_block(
        self, node: SyntaxNode, genealogy: Genealogy
    ) -> None:
        """Parse un bloc notes de base de données et l'ajoute aux métadonnées"""
        tokens = node.tokens

        # Extraire le contenu des notes
        notes_content: List[str] = []
        notes_agg = 0
        in_content = False

        for token in tokens:
            if token.type == TokenType.NOTES_DB:
                in_content = True
                continue
            elif token.type == TokenType.END_NOTES_DB:
                break
            elif in_content and token.type not in [
                TokenType.NEWLINE,
                TokenType.WHITESPACE,
            ]:
                notes_agg, stop = _bounded_append_text_fragment(
                    notes_content,
                    notes_agg,
                    token.value,
                    inter_fragment_sep_len=1,
                    max_fragments=_TEXT_AGGREGATE_MAX_FRAGMENTS,
                    max_aggregate_chars=_TEXT_AGGREGATE_MAX_CHARS,
                    log_context="Bloc notes-db",
                )
                if stop:
                    break

        if notes_content:
            # Stocker les notes de base de données dans les métadonnées
            if not hasattr(genealogy.metadata, "database_notes"):
                genealogy.metadata.database_notes = []
            genealogy.metadata.database_notes.append(" ".join(notes_content))

    def _parse_extended_page_block(
        self, node: SyntaxNode, persons: dict, genealogy: Genealogy
    ) -> None:
        """Parse un bloc page étendue et l'associe à la personne correspondante"""
        tokens = node.tokens

        # Extraire le nom de la personne
        if (
            len(tokens) >= 3
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.IDENTIFIER
        ):
            last_name = tokens[1].value
            first_name = tokens[2].value
            occurrence_num = 0

            # Vérifier s'il y a un numéro d'occurrence
            if len(tokens) >= 4 and tokens[3].type == TokenType.NUMBER:
                occurrence_str = tokens[3].value.lstrip(".")
                try:
                    occurrence_num = int(occurrence_str)
                except ValueError:
                    occurrence_num = 0

            person_id = self._get_or_create_person(
                last_name, first_name, occurrence_num, persons, genealogy
            )

            # Extraire le contenu de la page
            page_content: List[str] = []
            page_agg = 0
            in_content = False

            for token in tokens:
                if token.type == TokenType.PAGE_EXT:
                    in_content = True
                    continue
                elif token.type == TokenType.END_PAGE_EXT:
                    break
                elif in_content and token.type not in [
                    TokenType.NEWLINE,
                    TokenType.WHITESPACE,
                ]:
                    page_agg, stop = _bounded_append_text_fragment(
                        page_content,
                        page_agg,
                        token.value,
                        inter_fragment_sep_len=1,
                        max_fragments=_TEXT_AGGREGATE_MAX_FRAGMENTS,
                        max_aggregate_chars=_TEXT_AGGREGATE_MAX_CHARS,
                        log_context="Page étendue",
                    )
                    if stop:
                        break

            if page_content:
                # Stocker le contenu de la page dans les métadonnées de la personne
                person = persons[person_id]
                if "extended_page" not in person.metadata:
                    person.metadata["extended_page"] = []
                person.metadata["extended_page"].append(" ".join(page_content))

    def _parse_wizard_note_block(
        self, node: SyntaxNode, persons: dict, genealogy: Genealogy
    ) -> None:
        """Parse un bloc note de wizard et l'ajoute aux notes de la personne"""
        tokens = node.tokens

        # Extraire le nom de la personne
        if (
            len(tokens) >= 3
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.IDENTIFIER
        ):
            last_name = tokens[1].value
            first_name = tokens[2].value
            occurrence_num = 0

            # Vérifier s'il y a un numéro d'occurrence
            if len(tokens) >= 4 and tokens[3].type == TokenType.NUMBER:
                occurrence_str = tokens[3].value.lstrip(".")
                try:
                    occurrence_num = int(occurrence_str)
                except ValueError:
                    occurrence_num = 0

            person_id = self._get_or_create_person(
                last_name, first_name, occurrence_num, persons, genealogy
            )

            # Extraire le contenu des notes de wizard
            wizard_content: List[str] = []
            wiz_agg = 0
            in_content = False

            for token in tokens:
                if token.type == TokenType.WIZARD_NOTE:
                    in_content = True
                    continue
                elif token.type == TokenType.END_WIZARD_NOTE:
                    break
                elif in_content and token.type not in [
                    TokenType.NEWLINE,
                    TokenType.WHITESPACE,
                ]:
                    wiz_agg, stop = _bounded_append_text_fragment(
                        wizard_content,
                        wiz_agg,
                        token.value,
                        inter_fragment_sep_len=1,
                        max_fragments=_TEXT_AGGREGATE_MAX_FRAGMENTS,
                        max_aggregate_chars=_TEXT_AGGREGATE_MAX_CHARS,
                        log_context="Note wizard",
                    )
                    if stop:
                        break

            if wizard_content:
                # Ajouter les notes de wizard avec un tag spécial
                person = persons[person_id]
                wizard_note = f"[Wizard] {' '.join(wizard_content)}"
                person.add_note(wizard_note)

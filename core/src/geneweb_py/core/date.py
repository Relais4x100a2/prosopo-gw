"""
Modèle Date pour le format GeneWeb

Ce module implémente la représentation et le parsing des dates dans le format .gw,
avec support des calendriers multiples, préfixes et dates textuelles.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from .exceptions import UnsupportedCalendarError

# Regex précompilée pour les dates textuelles 0(texte)
TEXT_DATE_RE = re.compile(r"^0\((.+)\)$")


class DatePrefix(Enum):
    """Préfixes de date supportés par GeneWeb"""

    ABOUT = "~"  # ~10/5/1990
    MAYBE = "?"  # ?10/5/1990
    BEFORE = "<"  # <10/5/1990
    AFTER = ">"  # >10/5/1990
    OR = "|"  # 10/5/1990|1991
    BETWEEN = ".."  # 10/5/1990..1991


class CalendarType(Enum):
    """Types de calendriers supportés"""

    GREGORIAN = ""  # Par défaut
    JULIAN = "J"  # Julien
    FRENCH_REPUBLICAN = "F"  # Républicain français
    HEBREW = "H"  # Hébreu


class DeathType(Enum):
    """Types de décès avec préfixes spéciaux"""

    NORMAL = ""  # Normal
    KILLED = "k"  # Tué
    MURDERED = "m"  # Assassiné
    EXECUTED = "e"  # Exécuté
    DISAPPEARED = "s"  # Disparu


# Premier jour (1er vendémiaire) des années républicaines I à XIV ; l'an XIV
# s'arrête au 31 décembre 1805 (retour au calendrier grégorien).
_REPUBLICAN_YEAR_STARTS = {
    1: date(1792, 9, 22), 2: date(1793, 9, 22), 3: date(1794, 9, 22),
    4: date(1795, 9, 23), 5: date(1796, 9, 22), 6: date(1797, 9, 22),
    7: date(1798, 9, 22), 8: date(1799, 9, 23), 9: date(1800, 9, 23),
    10: date(1801, 9, 23), 11: date(1802, 9, 23), 12: date(1803, 9, 24),
    13: date(1804, 9, 23), 14: date(1805, 9, 23),
}  # fmt: skip
_REPUBLICAN_LAST_DAY = date(1805, 12, 31)


def _republican_complementary_days(year: int) -> int:
    """Nombre de jours complémentaires (5, ou 6 les années sextiles III, VII, XI)"""
    return 6 if year in (3, 7, 11) else 5


def _shift_years(day: date, years: int) -> date:
    """Décale d'un nombre d'années (29 février → 28 février si besoin)"""
    year = min(max(day.year + years, date.min.year), date.max.year)
    try:
        return day.replace(year=year)
    except ValueError:
        return day.replace(year=year, day=28)


@dataclass
class Date:
    """Représentation d'une date dans le format GeneWeb

    Supporte les formats européens (dd/mm/yyyy), les préfixes (~, ?, <, >),
    les calendriers multiples et les dates textuelles.
    """

    # Composants de date
    day: int | None = None
    month: int | None = None
    year: int | None = None

    # Préfixes et modificateurs
    prefix: DatePrefix | None = None
    calendar: CalendarType = CalendarType.GREGORIAN

    # Dates alternatives (pour OR et BETWEEN)
    alternative_dates: list["Date"] = field(default_factory=list)

    # Date textuelle (format 0(5_Mai_1990))
    text_date: str | None = None

    # Type de décès (pour les dates de décès)
    death_type: DeathType = DeathType.NORMAL

    # Date inconnue mais obligatoire
    is_unknown: bool = False

    # Chaîne telle qu'écrite dans le .gw (renseignée par parse ; hors comparaison)
    raw_text: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        """Validation et normalisation après initialisation"""
        if self.is_unknown:
            self.day = self.month = self.year = None
            self.text_date = None

        # Validation de cohérence
        if self.day is not None and (self.day < 1 or self.day > 31):
            raise ValueError(f"Jour invalide: {self.day}")

        # 13 mois : jours complémentaires (républicain), année embolismique (hébreu)
        has_month_13 = self.calendar in (
            CalendarType.FRENCH_REPUBLICAN,
            CalendarType.HEBREW,
        )
        max_month = 13 if has_month_13 else 12
        if self.month is not None and (self.month < 1 or self.month > max_month):
            raise ValueError(f"Mois invalide: {self.month}")

        if self.year is not None and self.year < 1:
            raise ValueError(f"Année invalide: {self.year}")

    @property
    def is_complete(self) -> bool:
        """Vérifie si la date est complète (jour, mois, année)"""
        return all(x is not None for x in [self.day, self.month, self.year])

    @property
    def is_partial(self) -> bool:
        """Vérifie si la date est partielle (mois/année ou année seulement)"""
        if self.is_unknown or self.text_date:
            return False
        return self.year is not None and (self.day is None or self.month is None)

    def sort_year(self) -> int | None:
        """Année utilisée pour le tri et les filtres par plage (ex.: recherche API).

        Les dates textuelles ou inconnues ne fournissent pas d'année exploitable ;
        les dates OR/BETWEEN utilisent l'année du segment principal.

        Returns:
            Année grégorienne principale ou None si non déterminable.
        """
        if self.is_unknown or self.text_date:
            return None
        return self.year

    def filter_years_for_range(self) -> list[int]:
        """Années candidates pour un filtre par plage [début, fin].

        Inclut l'année du segment principal et, pour OR/BETWEEN, les années issues
        des segments ``alternative_dates`` (sans fusion ni dédoublonnage).

        Returns:
            Liste vide si aucune année exploitable.
        """
        years: list[int] = []
        y = self.sort_year()
        if y is not None:
            years.append(y)
        for alt in self.alternative_dates:
            ay = alt.sort_year()
            if ay is not None:
                years.append(ay)
        return years

    @property
    def display_text(self) -> str:
        """Retourne la représentation textuelle de la date"""
        if self.text_date:
            return f"0({self.text_date})"

        if self.is_unknown:
            return "0"

        parts = []

        # Ajouter le préfixe (sauf pour OR et BETWEEN qui sont gérés séparément)
        if self.prefix and self.prefix not in [DatePrefix.OR, DatePrefix.BETWEEN]:
            parts.append(self.prefix.value)

        # Ajouter le type de décès
        if self.death_type != DeathType.NORMAL:
            parts.append(self.death_type.value)

        # Construire la date
        date_parts = []
        if self.day:
            date_parts.append(f"{self.day:02d}")
        if self.month:
            date_parts.append(f"{self.month:02d}")
        if self.year:
            date_parts.append(f"{self.year:04d}")

        if date_parts:
            date_str = "/".join(date_parts)
            parts.append(date_str)

        # Ajouter le calendrier
        if self.calendar != CalendarType.GREGORIAN:
            parts.append(self.calendar.value)

        # Ajouter les dates alternatives
        if self.alternative_dates:
            if self.prefix == DatePrefix.OR:
                # Pour OR, construire la chaîne avec le séparateur |
                alt_texts = [alt.display_text for alt in self.alternative_dates]
                parts.append("|".join(alt_texts))
            elif self.prefix == DatePrefix.BETWEEN:
                if self.alternative_dates:
                    parts.append(f"..{self.alternative_dates[0].display_text}")

        result = "".join(parts)

        # Pour OR, reconstruire la chaîne avec le bon format
        if self.prefix == DatePrefix.OR and self.alternative_dates:
            main_date = "".join(parts[:-1])  # Tous sauf la dernière partie
            alt_texts = [alt.display_text for alt in self.alternative_dates]
            result = f"{main_date}|{'|'.join(alt_texts)}"

        return result

    def to_bounds(self, fuzzy_window_years: int = 5) -> tuple[date | None, date | None]:
        """Intervalle grégorien ``(date_min, date_max)`` couvert par la date

        Une date partielle couvre toute sa période (année → 1er janvier au
        31 décembre). Règles (modèle Chronologia §5.6) :

        - ``~`` élargit de ``fuzzy_window_years`` ans de chaque côté ;
        - ``?`` garde la précision déclarée (la crédibilité se règle ailleurs) ;
        - ``<`` : borne basse ouverte, borne haute = veille du début de la date ;
        - ``>`` : borne haute ouverte, borne basse = lendemain de la fin de la date ;
        - ``|`` et ``..`` : enveloppe de toutes les alternatives.

        Le calendrier julien est converti en grégorien (proleptique) ; le
        calendrier républicain l'est par table pour les ans I à XIV.

        Args:
            fuzzy_window_years: demi-fenêtre appliquée aux dates ``~``.

        Returns:
            ``(None, None)`` si la date est inconnue ou en texte libre.

        Raises:
            UnsupportedCalendarError: calendrier hébraïque, ou année républicaine
                hors de I–XIV.
            ValueError: date impossible (ex. 31 février) ou hors de 1..9999.
        """
        if self.is_unknown or self.text_date or self.year is None:
            return (None, None)
        if self.calendar == CalendarType.HEBREW or (
            self.calendar == CalendarType.FRENCH_REPUBLICAN
            and any(
                d.year not in _REPUBLICAN_YEAR_STARTS
                for d in [self, *self.alternative_dates]
                if d.year is not None
            )
        ):
            raise UnsupportedCalendarError(
                f"Le calendrier {self.calendar.name.lower()} n'est pas supporté "
                "pour le calcul de bornes automatiques",
            )

        # Les alternatives (| et ..) héritent du calendrier de la date principale
        spans = [self._span(self.year, self.month, self.day)]
        spans += [
            self._span(alt.year, alt.month, alt.day)
            for alt in self.alternative_dates
            if alt.year is not None
        ]
        low = min(start for start, _ in spans)
        high = max(end for _, end in spans)

        if self.prefix == DatePrefix.ABOUT:
            return (
                _shift_years(low, -fuzzy_window_years),
                _shift_years(high, fuzzy_window_years),
            )
        if self.prefix == DatePrefix.BEFORE:
            return (None, low - timedelta(days=1))
        if self.prefix == DatePrefix.AFTER:
            return (high + timedelta(days=1), None)
        return (low, high)

    def _span(self, year: int, month: int | None, day: int | None) -> tuple[date, date]:
        """Premier et dernier jour (grégoriens) de la période, dans le calendrier"""
        if self.calendar == CalendarType.FRENCH_REPUBLICAN:
            return self._republican_span(year, month, day)
        if month is None:
            first, last = (year, 1, 1), (year, 12, 31)
        elif day is None:
            first = (year, month, 1)
            last = (year, month, self._days_in_month(year, month))
        else:
            first = last = (year, month, day)
        return self._to_gregorian(*first), self._to_gregorian(*last)

    def _republican_span(
        self, year: int, month: int | None, day: int | None
    ) -> tuple[date, date]:
        """Période républicaine en jours grégoriens (l'an XIV s'arrête au 31/12/1805)"""
        start = _REPUBLICAN_YEAR_STARTS[year]
        complementary = _republican_complementary_days(year)
        if month is None:
            first_idx, last_idx = 0, 359 + complementary
        else:
            length = complementary if month == 13 else 30
            if day is not None and day > length:
                raise ValueError(f"Jour invalide: {day}/{month}/{year}")
            first_idx = (month - 1) * 30 + (day - 1 if day else 0)
            last_idx = first_idx if day else first_idx + length - 1
        first = start + timedelta(days=first_idx)
        last = min(start + timedelta(days=last_idx), _REPUBLICAN_LAST_DAY)
        if first > _REPUBLICAN_LAST_DAY:
            raise ValueError(f"Date républicaine hors période: {month}/{year}")
        return first, last

    def _days_in_month(self, year: int, month: int) -> int:
        if month == 2:
            if self.calendar == CalendarType.JULIAN:
                leap = year % 4 == 0
            else:
                leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
            return 29 if leap else 28
        return 30 if month in (4, 6, 9, 11) else 31

    def _to_gregorian(self, year: int, month: int, day: int) -> date:
        if self.calendar != CalendarType.JULIAN:
            return date(year, month, day)
        if day > self._days_in_month(year, month):
            raise ValueError(f"Jour invalide: {day}/{month}/{year}")
        # Jour julien -> ordinal grégorien (Python compte le 01/01/0001 grégorien = 1)
        a = (14 - month) // 12
        y = year + 4800 - a
        m = month + 12 * a - 3
        julian_day_number = day + (153 * m + 2) // 5 + 365 * y + y // 4 - 32083
        return date.fromordinal(julian_day_number - 1721425)

    def to_iso_format(self) -> str | None:
        """Convertit la date au format ISO (YYYY-MM-DD) si possible"""
        if not self.is_complete or self.is_unknown:
            return None

        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    @classmethod
    def parse(cls, date_str: str | None) -> "Date":
        """Parse une chaîne de date au format GeneWeb et garde le texte d'origine

        ``raw_text`` reçoit la chaîne écrite (sans espaces de bord), ``None`` si
        ``date_str`` est ``None``. Voir ``_parse_impl`` pour le détail des formats.
        """
        resultat = cls._parse_impl(date_str)
        if date_str is not None:
            resultat.raw_text = date_str.strip()
        return resultat

    @classmethod
    def _parse_impl(cls, date_str: str | None) -> "Date":
        """Parse une chaîne de date au format GeneWeb

        Args:
            date_str: Chaîne de date au format GeneWeb (ex. ``25/12/1990``,
                ``~10/5/1990``, ``0(5_Mai_1990)``).

        Returns:
            Instance de Date parsée

        Raises:
            ValueError: Si la date ne peut pas être parsée
        """
        # Support None → date inconnue
        if date_str is None:
            return cls(is_unknown=True)

        # Nettoyer la chaîne de date; si vide ⇒ date inconnue
        date_str = date_str.strip()

        # Support des dates vides (ex: "#deat" sans date) → date inconnue
        if date_str == "":
            return cls(is_unknown=True)

        # Date inconnue
        if date_str == "0":
            return cls(is_unknown=True)

        # Date textuelle (0(texte))
        text_match = TEXT_DATE_RE.match(date_str)
        if text_match:
            return cls(text_date=text_match.group(1))

        # Parser les préfixes et modificateurs
        prefix = None
        death_type = DeathType.NORMAL
        calendar = CalendarType.GREGORIAN

        # Vérifier les préfixes
        if date_str.startswith("~"):
            prefix = DatePrefix.ABOUT
            date_str = date_str[1:]
        elif date_str.startswith("?"):
            prefix = DatePrefix.MAYBE
            date_str = date_str[1:]
        elif date_str.startswith("<"):
            prefix = DatePrefix.BEFORE
            date_str = date_str[1:]
        elif date_str.startswith(">"):
            prefix = DatePrefix.AFTER
            date_str = date_str[1:]

        # Vérifier les types de décès
        if date_str.startswith("k"):
            death_type = DeathType.KILLED
            date_str = date_str[1:]
        elif date_str.startswith("m"):
            death_type = DeathType.MURDERED
            date_str = date_str[1:]
        elif date_str.startswith("e"):
            death_type = DeathType.EXECUTED
            date_str = date_str[1:]
        elif date_str.startswith("s"):
            death_type = DeathType.DISAPPEARED
            date_str = date_str[1:]

        # Vérifier le calendrier
        if date_str.endswith("J"):
            calendar = CalendarType.JULIAN
            date_str = date_str[:-1]
        elif date_str.endswith("F"):
            calendar = CalendarType.FRENCH_REPUBLICAN
            date_str = date_str[:-1]
        elif date_str.endswith("H"):
            calendar = CalendarType.HEBREW
            date_str = date_str[:-1]

        # Parser les dates avec OR ou BETWEEN
        alternative_dates = []
        if "|" in date_str:
            prefix = DatePrefix.OR
            parts = date_str.split("|")
            date_str = parts[0]
            for part in parts[1:]:
                alt_date = cls.parse(part.strip())
                alternative_dates.append(alt_date)
        elif ".." in date_str:
            prefix = DatePrefix.BETWEEN
            parts = date_str.split("..")
            date_str = parts[0]
            if date_str[-1:] in ("J", "F", "H"):
                date_str = date_str[:-1]  # calendrier écrit sur la première borne
            if len(parts) > 1:
                # Borne de fin : année seule ou date complète, même calendrier
                fin = cls._parse_impl(parts[1] + calendar.value)
                fin.calendar = (
                    CalendarType.GREGORIAN
                )  # le calendrier reste porté par la date principale
                alternative_dates.append(fin)

        # Parser la date principale avec gestion des champs vides
        if "/" in date_str:
            parts = date_str.split("/")

            # Filtrer les parties vides et convertir en entiers
            def safe_int(value):
                """Convertit une chaîne en entier, retourne None si vide ou invalide"""
                if not value or value.strip() == "":
                    return None
                try:
                    return int(value.strip())
                except ValueError:
                    return None

            if len(parts) == 3:
                day, month, year = map(safe_int, parts)

                # Si tous les champs sont vides, c'est une date inconnue
                if day is None and month is None and year is None:
                    return cls(is_unknown=True)

                return cls(
                    day=day,
                    month=month,
                    year=year,
                    prefix=prefix,
                    calendar=calendar,
                    alternative_dates=alternative_dates,
                    death_type=death_type,
                )
            elif len(parts) == 2:
                month, year = map(safe_int, parts)

                # Si les deux champs sont vides, c'est une date inconnue
                if month is None and year is None:
                    return cls(is_unknown=True)

                return cls(
                    month=month,
                    year=year,
                    prefix=prefix,
                    calendar=calendar,
                    alternative_dates=alternative_dates,
                    death_type=death_type,
                )
        elif date_str.isdigit():
            # Année seulement
            year = int(date_str)
            return cls(
                year=year,
                prefix=prefix,
                calendar=calendar,
                alternative_dates=alternative_dates,
                death_type=death_type,
            )

        # Si on arrive ici et que la chaîne n'est pas vide, c'est un format non reconnu
        # Mais on peut essayer de parser comme année si c'est numérique
        if date_str.replace("-", "").replace(".", "").isdigit():
            try:
                year = int(float(date_str))
                return cls(
                    year=year,
                    prefix=prefix,
                    calendar=calendar,
                    alternative_dates=alternative_dates,
                    death_type=death_type,
                )
            except ValueError:
                pass

        raise ValueError(f"Format de date non reconnu: {date_str}")

    @classmethod
    def parse_with_fallback(cls, date_str: str) -> "Date":
        """Parse une date avec gestion gracieuse des erreurs

        Args:
            date_str: Chaîne de date à parser

        Returns:
            Instance de Date parsée ou date inconnue en cas d'erreur
        """
        try:
            return cls.parse(date_str)
        except ValueError:
            # En cas d'erreur, date inconnue ; le texte écrit reste disponible
            return cls(is_unknown=True, raw_text=date_str.strip())

    def is_after(self, other: "Date") -> bool:
        """Vérifie si cette date est après une autre date

        Args:
            other: L'autre date à comparer

        Returns:
            True si cette date est après l'autre
        """
        # Si l'une des dates est inconnue, on ne peut pas comparer
        if self.is_unknown or other.is_unknown:
            return False

        # Comparer par année si disponible
        if self.year and other.year:
            if self.year != other.year:
                return self.year > other.year

            # Si même année, comparer par mois
            if self.month and other.month:
                if self.month != other.month:
                    return self.month > other.month

                # Si même mois, comparer par jour
                if self.day and other.day:
                    return self.day > other.day

        # Par défaut, on ne peut pas déterminer
        return False

    def is_before(self, other: "Date") -> bool:
        """Vérifie si cette date est avant une autre date

        Args:
            other: L'autre date à comparer

        Returns:
            True si cette date est avant l'autre
        """
        # Si l'une des dates est inconnue, on ne peut pas comparer
        if self.is_unknown or other.is_unknown:
            return False

        # Comparer par année si disponible
        if self.year and other.year:
            if self.year != other.year:
                return self.year < other.year

            # Si même année, comparer par mois
            if self.month and other.month:
                if self.month != other.month:
                    return self.month < other.month

                # Si même mois, comparer par jour
                if self.day and other.day:
                    return self.day < other.day

        # Par défaut, on ne peut pas déterminer
        return False

    def __str__(self) -> str:
        """Représentation string de la date"""
        return self.display_text

    def __repr__(self) -> str:
        """Représentation pour debug"""
        return f"Date('{self.display_text}')"

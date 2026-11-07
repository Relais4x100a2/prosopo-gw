# Dockerfile pour GeneWeb 7.0.0 - Installation utilisateur conforme
# Basé sur : https://geneweb.github.io/installation/index.html (section "Installation (for users)")
# Téléchargement du binaire pré-compilé depuis : https://github.com/geneweb/geneweb/releases/download/v7.0.0/geneweb-linux-88536ed4.zip

FROM debian:bookworm-slim

# Variables d'environnement
ENV GW_PORT=2317
ENV GW_LANG=fr
ENV GW_BASES_DIR=/opt/geneweb/bases
ENV GENEWEB_VERSION=v7.0.0

# Installation des dépendances système
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Création des répertoires et de l'utilisateur geneweb
RUN useradd -m -s /bin/bash geneweb && \
    mkdir -p /opt/geneweb ${GW_BASES_DIR} && \
    chown -R geneweb:geneweb /opt/geneweb

# Téléchargement et installation du binaire GeneWeb 7.0.0 pré-compilé
# Conforme à la documentation officielle pour les utilisateurs
WORKDIR /opt/geneweb
RUN wget -O geneweb-linux.zip "https://github.com/geneweb/geneweb/releases/download/${GENEWEB_VERSION}/geneweb-linux-88536ed4.zip" && \
    unzip geneweb-linux.zip && \
    rm geneweb-linux.zip && \
    mv distribution/* . && \
    rmdir distribution && \
    chmod +x gw/* gwd gwsetup && \
    chown -R geneweb:geneweb /opt/geneweb

# Correction du problème welcome.txt - copier depuis gw/etc
RUN cp gw/etc/welcome.txt . && chmod 644 welcome.txt && chown geneweb:geneweb welcome.txt

# Port d'écoute
EXPOSE ${GW_PORT}

# Passage à l'utilisateur geneweb
USER geneweb

# Création du script de démarrage
RUN echo '#!/bin/bash\n\
cd /opt/geneweb\n\
echo "Démarrage de GeneWeb 7.0.0 (binaire officiel)..."\n\
echo "Port: $GW_PORT"\n\
echo "Répertoire des bases: $GW_BASES_DIR"\n\
echo "Langue: $GW_LANG"\n\
./gw/gwd -hd /opt/geneweb -bd "$GW_BASES_DIR" -p "$GW_PORT" -lang "$GW_LANG" "$@"\n\
' > /opt/geneweb/start-geneweb.sh && chmod +x /opt/geneweb/start-geneweb.sh

# Healthcheck pour vérifier que le serveur répond
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${GW_PORT}/ || exit 1

# Commande par défaut
CMD ["/opt/geneweb/start-geneweb.sh"]

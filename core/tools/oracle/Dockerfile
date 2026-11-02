# Oracle GeneWeb : binaires officiels du tag v7.1.0-beta2 (gwc, gwu).
# Les sources du même tag font foi pour toute règle recopiée dans la doc.
FROM debian:bookworm-slim

ARG GENEWEB_TAG=v7.1.0-beta2
ARG GENEWEB_ZIP=geneweb-7.1.0-beta2-linux.zip

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/geneweb
RUN curl -fsSL -o gw.zip \
        "https://github.com/geneweb/geneweb/releases/download/${GENEWEB_TAG}/${GENEWEB_ZIP}" \
    && unzip -q gw.zip && rm gw.zip \
    && GWC="$(find /opt/geneweb -name gwc -type f | head -1)" \
    && test -n "$GWC" \
    && chmod +x "$(dirname "$GWC")"/* \
    && ln -s "$(dirname "$GWC")" /opt/geneweb/bin

ENV PATH="/opt/geneweb/bin:${PATH}"

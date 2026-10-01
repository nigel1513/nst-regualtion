# HWP/HWPX → PDF 보기용 사본 변환기: LibreOffice(headless) + H2Orestart(HWP 읽기 확장)
FROM debian:bookworm-slim
ARG H2O_VERSION=v0.7.14
RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-writer-nogui libreoffice-java-common default-jre-headless \
      fonts-nanum fonts-noto-cjk curl ca-certificates \
 && curl -fsSL -o /tmp/H2Orestart.oxt https://github.com/ebandal/H2Orestart/releases/download/${H2O_VERSION}/H2Orestart.oxt \
 && unopkg add --shared /tmp/H2Orestart.oxt && rm /tmp/H2Orestart.oxt \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
WORKDIR /work
ENTRYPOINT ["soffice", "-env:UserInstallation=file:///tmp/lo-profile", "--headless", "--norestore", "--convert-to", "pdf", "--outdir", "/work/out"]

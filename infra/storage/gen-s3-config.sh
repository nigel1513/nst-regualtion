#!/usr/bin/env bash
# .env의 REG_S3_ACCESS_KEY/REG_S3_SECRET_KEY로 SeaweedFS S3 인증 설정을 만든다 (결과 파일은 gitignore).
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a
cat > infra/storage/s3.json <<JSON
{"identities":[{"name":"regulation","credentials":[{"accessKey":"${REG_S3_ACCESS_KEY}","secretKey":"${REG_S3_SECRET_KEY}"}],"actions":["Admin","Read","Write","List","Tagging"]}]}
JSON
chmod 600 infra/storage/s3.json

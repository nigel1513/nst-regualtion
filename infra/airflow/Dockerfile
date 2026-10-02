# infra/airflow/Dockerfile
# Airflow 3 + reg 패키지 (일 배치, spec §2.1). 빌드: bash scripts/airflow.sh build
# 코드(src)는 이미지에 굽는다 → 코드가 바뀌면 다시 빌드. config/와 airflow/dags/는 compose가 마운트한다.
ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.13
FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}
ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.13
ENV TZ=Asia/Seoul
COPY --chown=airflow:0 infra/airflow/requirements-batch.txt /tmp/requirements-batch.txt
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /tmp/requirements-batch.txt \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"
COPY --chown=airflow:0 pyproject.toml /opt/nst-regulation/pyproject.toml
COPY --chown=airflow:0 src /opt/nst-regulation/src
COPY --chown=airflow:0 config /opt/nst-regulation/config
COPY --chown=airflow:0 infra/airflow/init.sh /opt/nst-regulation/infra/airflow/init.sh
# fastapi 충돌 때문에 --no-deps (결정 8). -e: reg 코드가 /opt/nst-regulation/src에 있어야 config/를 찾는다(결정 9).
RUN pip install --no-cache-dir --no-deps -e /opt/nst-regulation
COPY --chown=airflow:0 airflow/dags /opt/airflow/dags

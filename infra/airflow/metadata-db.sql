-- infra/airflow/metadata-db.sql — Airflow 메타데이터 DB (spec §2.1). psql 변수 :pw 필요. 여러 번 실행해도 같다.
SELECT format('CREATE ROLE reg_airflow LOGIN PASSWORD %L', :'pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reg_airflow') \gexec
SELECT format('ALTER ROLE reg_airflow LOGIN PASSWORD %L', :'pw') \gexec
SELECT 'CREATE DATABASE reg_airflow OWNER reg_airflow ENCODING ''UTF8'' TEMPLATE template0'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'reg_airflow') \gexec
REVOKE ALL ON DATABASE reg_airflow FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE reg_airflow TO reg_airflow;
\connect reg_airflow
ALTER SCHEMA public OWNER TO reg_airflow;

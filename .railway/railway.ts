// Optional IaC blueprint. Use a NEW empty project and review `railway config plan`.
// Set the preserve() variables in Railway first; secrets never belong in this file.
import { defineRailway, github, image, preserve, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const region = "europe-west4";
  const data = volume("postgres-data", { region, sizeMB: 1024 });
  const postgres = service("postgres", {
    source: image("pgvector/pgvector:0.8.7-pg17", { autoUpdates: { type: "disabled" } }),
    replicas: { [region]: 1 },
    deploy: { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 10, sleepApplication: false },
    volumeMounts: { "/var/lib/postgresql/data": data },
    env: {
      POSTGRES_USER: "railway_admin", POSTGRES_DB: "marketmind", POSTGRES_PASSWORD: preserve(),
      PGDATA: "/var/lib/postgresql/data/pgdata",
      PGHOST: "${{postgres.RAILWAY_PRIVATE_DOMAIN}}", PGPORT: "5432", PGDATABASE: "marketmind",
      DATABASE_URL: "postgresql://railway_admin:${{postgres.POSTGRES_PASSWORD}}@${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/marketmind",
    },
  });
  const backendSource = github("lindahmed/marketmind", { branch: "main", rootDirectory: "backend", checkSuites: true });
  const build = { builder: "DOCKERFILE" as const, dockerfilePath: "Dockerfile", watchPatterns: ["/backend/**"] };
  const deploy = { restartPolicyType: "ON_FAILURE" as const, restartPolicyMaxRetries: 10, sleepApplication: false };
  const migration = service("migration", {
    source: backendSource, build, start: "python -m app.migrate", replicas: { [region]: 1 },
    deploy: { restartPolicyType: "NEVER", sleepApplication: false },
    env: {
      MIGRATION_DATABASE_URL: postgres.env.DATABASE_URL,
      API_DATABASE_PASSWORD: preserve(), WORKER_DATABASE_PASSWORD: preserve(),
    },
  });
  const backend = service("backend", {
    source: backendSource, build, deploy, replicas: { [region]: 1 },
    start: "sh -c 'exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log --no-proxy-headers'",
    healthcheck: "/health", healthcheckTimeout: 120,
    env: {
      ENVIRONMENT: "production", SERVICE_ROLE: "api", PORT: "8000", COOKIE_SECURE: "true",
      WORKFLOW_WORKER_ENABLED: "false", JWT_SECRET: preserve(), ALLOWED_ORIGINS: preserve(),
      DATABASE_URL: "postgresql://marketmind_api:${{migration.API_DATABASE_PASSWORD}}@${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/marketmind",
      EMBEDDING_PROVIDER: "disabled", INVESTIGATION_PROVIDER: "disabled", STRATEGY_PROVIDER: "disabled",
      OPENAI_API_KEY: preserve(), N8N_WEBHOOK_URL: preserve(), N8N_WEBHOOK_TOKEN: preserve(), N8N_CALLBACK_TOKEN: preserve(),
      DB_POOL_SIZE: "5", DB_MAX_OVERFLOW: "2",
    },
  });
  const worker = service("worker", {
    source: backendSource, build, deploy, replicas: { [region]: 1 },
    start: "python -m app.worker", healthcheck: "/health", healthcheckTimeout: 120,
    env: {
      ENVIRONMENT: "production", SERVICE_ROLE: "worker", PORT: "8000", COOKIE_SECURE: "true",
      WORKFLOW_WORKER_ENABLED: "false", JWT_SECRET: backend.env.JWT_SECRET,
      ALLOWED_ORIGINS: backend.env.ALLOWED_ORIGINS,
      DATABASE_URL: "postgresql://marketmind_worker:${{migration.WORKER_DATABASE_PASSWORD}}@${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/marketmind",
      OPENAI_API_KEY: backend.env.OPENAI_API_KEY,
      EMBEDDING_PROVIDER: backend.env.EMBEDDING_PROVIDER, INVESTIGATION_PROVIDER: backend.env.INVESTIGATION_PROVIDER,
      STRATEGY_PROVIDER: backend.env.STRATEGY_PROVIDER,
      WORKER_POLL_SECONDS: "2", WORKER_LEASE_SECONDS: "300", WORKER_HEARTBEAT_SECONDS: "30",
      DB_POOL_SIZE: "5", DB_MAX_OVERFLOW: "2",
    },
  });
  const frontend = service("frontend", {
    source: github("lindahmed/marketmind", { branch: "main", rootDirectory: "frontend", checkSuites: true }),
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile", watchPatterns: ["/frontend/**"] },
    start: "node server.js", healthcheck: "/health", healthcheckTimeout: 120,
    replicas: { [region]: 1 }, deploy,
    env: { PORT: "3000", DEPLOYMENT_ENVIRONMENT: "production", NEXT_PUBLIC_API_URL: "",
           BACKEND_API_URL: "http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000" },
  });
  return project("MarketMind", { resources: [postgres, data, migration, backend, worker, frontend] });
});

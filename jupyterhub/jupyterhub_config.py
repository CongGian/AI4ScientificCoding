import os

c.JupyterHub.authenticator_class = "oauthenticator.github.GitHubOAuthenticator"
c.GitHubOAuthenticator.oauth_callback_url = os.environ["OAUTH_CALLBACK_URL"]
c.GitHubOAuthenticator.client_id = os.environ["GITHUB_CLIENT_ID"]
c.GitHubOAuthenticator.client_secret = os.environ["GITHUB_CLIENT_SECRET"]
c.GitHubOAuthenticator.allowed_organizations = {"NCSU-NNDL-Spring26"}
c.GitHubOAuthenticator.scope = ["read:org"]
c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = "jupyterhub"
c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
c.DockerSpawner.image = "ai4scientificcoding-notebook:latest"
c.DockerSpawner.network_name = "jupyterhub-network"
c.DockerSpawner.remove = False
c.DockerSpawner.http_timeout = 300
c.DockerSpawner.extra_host_config = {"runtime": "nvidia"}

user_storage_root = os.environ.get("JUPYTERHUB_USER_STORAGE_ROOT", "/media/volume/jupyterhub/users")
llm_log_volume = os.environ.get("JUPYTERHUB_LLM_LOG_VOLUME", "jupyterhub-llm-logs")

c.DockerSpawner.volumes = {
    f"{user_storage_root}/{{username}}": "/home/jovyan/work",
    llm_log_volume: "/var/log/llm-proxy",
}

c.DockerSpawner.environment = {
    "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
    "JUPYTERHUB_USER": "{username}",
    "LLM_LOG_DIR": "/var/log/llm-proxy",
    "LLM_UPSTREAM_BASE_URL": os.environ.get("LLM_UPSTREAM_BASE_URL", "https://llm.jetstream-cloud.org/v1"),
    "LLM_PROXY_PORT": "8010",
    "OPENAI_BASE_URL": "http://127.0.0.1:8010/v1",
    "OPENAI_API_BASE": "http://127.0.0.1:8010/v1",
    "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", os.environ.get("CLINE_API_KEY", "proxy-local")),
    "CLINE_BASE_URL": "http://127.0.0.1:8010/v1",
    "CLINE_API_KEY": os.environ.get("CLINE_API_KEY", os.environ.get("OPENAI_API_KEY", "proxy-local")),
}

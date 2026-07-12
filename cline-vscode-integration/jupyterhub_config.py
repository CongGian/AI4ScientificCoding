import os

c.JupyterHub.authenticator_class = "oauthenticator.github.GitHubOAuthenticator"
c.GitHubOAuthenticator.oauth_callback_url = "https://srp-jupyterhub.nairr240257.projects.jetstream-cloud.org/hub/oauth_callback"
c.GitHubOAuthenticator.client_id = "YOUR_CLIENT_ID"
c.GitHubOAuthenticator.client_secret = "YOUR_CLIENT_SECRET"
c.Authenticator.allowed_users = ["lobaton", "darrendbutler", "qsamson"]
c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = "jupyterhub"
c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
c.DockerSpawner.image = "pytorch-cline:latest"
c.DockerSpawner.network_name = "jupyterhub-network"
c.DockerSpawner.remove = False
c.DockerSpawner.http_timeout = 300
c.DockerSpawner.extra_host_config = {"runtime": "nvidia"}

user_storage_volume_prefix = os.environ.get("JUPYTERHUB_USER_STORAGE_VOLUME_PREFIX", "jupyterhub-user")
llm_log_volume = os.environ.get("JUPYTERHUB_LLM_LOG_VOLUME", "jupyterhub-llm-logs")

c.DockerSpawner.volumes = {
	f"{user_storage_volume_prefix}-{{username}}": "/home/jovyan/work",
	llm_log_volume: "/var/log/llm-proxy",
}

c.DockerSpawner.environment = {
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

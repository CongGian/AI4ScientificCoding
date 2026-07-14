import os

def _allowed_organizations():
    orgs = os.environ.get(
        "GITHUB_ALLOWED_ORGS",
        "NCState-AI-Workshop,NCSU-NNDL-Spring26",
    )
    return {org.strip() for org in orgs.split(",") if org.strip()}

c.JupyterHub.authenticator_class = "oauthenticator.github.GitHubOAuthenticator"
c.GitHubOAuthenticator.oauth_callback_url = "https://srp-jupyterhub.nairr240257.projects.jetstream-cloud.org/hub/oauth_callback"
c.GitHubOAuthenticator.client_id = "YOUR_CLIENT_ID"
c.GitHubOAuthenticator.client_secret = "YOUR_CLIENT_SECRET"
c.GitHubOAuthenticator.allowed_organizations = _allowed_organizations()
c.GitHubOAuthenticator.scope = ["read:org", "user:email"]
c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = "jupyterhub"
c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
c.DockerSpawner.image = "pytorch-cline:latest"
c.DockerSpawner.network_name = "jupyterhub-network"
c.DockerSpawner.remove = False
c.DockerSpawner.http_timeout = 300
c.DockerSpawner.extra_host_config = {"runtime": "nvidia"}

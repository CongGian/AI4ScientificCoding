FROM quay.io/jupyter/pytorch-notebook:cuda12-python-3.12
USER root

RUN curl -fsSL https://code-server.dev/install.sh | sh
RUN pip install fastapi httpx jupyter-server-proxy uvicorn
RUN code-server --install-extension saoudrizwan.claude-dev

RUN conda install -c conda-forge nodejs -y && \
    npm install -g cline && \
    npm cache clean --force && \
    conda clean -afy

COPY llm-proxy /tmp/llm-proxy
RUN pip install --no-cache-dir /tmp/llm-proxy && rm -rf /tmp/llm-proxy

# Cline settings are written at container startup from environment variables.

RUN mkdir -p /home/jovyan/.jupyter && \
    echo 'c.ServerProxy.servers = {"vscode": {"command": ["code-server", "--auth", "none", "--bind-addr", "0.0.0.0:8080", "/home/jovyan"], "port": 8080, "launcher_entry": {"enabled": True, "title": "VS Code + Cline"}}}' \
    > /home/jovyan/.jupyter/jupyter_server_config.py

COPY start-code-server.sh /usr/local/bin/start-code-server.sh
RUN chmod +x /usr/local/bin/start-code-server.sh
RUN fix-permissions /home/jovyan && fix-permissions /opt/conda

USER ${NB_UID}
CMD ["bash", "-c", "/usr/local/bin/start-code-server.sh && start-notebook.py"]

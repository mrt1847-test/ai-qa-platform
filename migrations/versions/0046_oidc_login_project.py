"""Bind hosted OIDC login state to the project chosen at browser start."""


def apply(connection):
    connection.execute("ALTER TABLE oidc_login_states ADD COLUMN project_id TEXT")

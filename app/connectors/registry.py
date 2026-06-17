from app.connectors.slack import SlackConnector
from app.connectors.jira import JiraConnector

class ConnectorRegistry:
    def __init__(self):
        self.connectors = {
            "slack": SlackConnector(),
            "jira": JiraConnector()
        }

    def get_connector(self, connector_type: str):
        return self.connectors.get(connector_type)

# Create a global instance
connector_registry = ConnectorRegistry()
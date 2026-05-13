import logging

import requests


logger = logging.getLogger(__name__)


class TodoistService:
    BASE_URL = "https://api.todoist.com/api/v1"

    def __init__(self, api_token: str) -> None:
        self.api_token = api_token
        self.headers = {"Authorization": f"Bearer {self.api_token}"}

    def _get(self, endpoint: str, params: dict | None = None) -> list[dict]:
        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=30,
            )
        except requests.RequestException:
            logger.exception("Todoist request failed: %s params=%s", endpoint, params)
            raise

        if not response.ok:
            logger.error(
                "Todoist API request failed: endpoint=%s params=%s status=%s body=%s",
                endpoint,
                params,
                response.status_code,
                response.text,
            )
            raise Exception(
                f"Todoist API request failed: {response.status_code} {response.text}"
            )

        data = response.json()
        logger.info("Todoist request succeeded: %s params=%s", endpoint, params)
        return data.get("results", [])

    def get_tasks(self) -> list[dict]:
        return self._get("/tasks")

    def get_tasks_today(self) -> list[dict]:
        return self._get("/tasks", params={"filter": "today"})

    def get_projects(self) -> list[dict]:
        return self._get("/projects")

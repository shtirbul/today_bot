import requests


class TodoistService:
    BASE_URL = "https://api.todoist.com/api/v1"

    def __init__(self, api_token: str) -> None:
        self.api_token = api_token
        self.headers = {"Authorization": f"Bearer {self.api_token}"}

    def _get(self, endpoint: str, params: dict | None = None) -> list[dict]:
        response = requests.get(
            f"{self.BASE_URL}{endpoint}",
            headers=self.headers,
            params=params,
            timeout=30,
        )

        if not response.ok:
            raise Exception(
                f"Todoist API request failed: {response.status_code} {response.text}"
            )

        data = response.json()
        return data.get("results", [])

    def get_tasks(self) -> list[dict]:
        return self._get("/tasks")

    def get_tasks_today(self) -> list[dict]:
        return self._get("/tasks", params={"filter": "today"})

    def get_projects(self) -> list[dict]:
        return self._get("/projects")

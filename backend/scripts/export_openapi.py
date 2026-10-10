"""Print the OpenAPI document (used to generate the frontend's TypeScript types)."""
import json

from app.main import app

print(json.dumps(app.openapi(), indent=1))

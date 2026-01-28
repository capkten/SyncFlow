import os
import unittest

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from backend.utils.auth import require_api_token


class TestApiAuth(unittest.TestCase):
    def setUp(self):
        os.environ['TONGBU_API_TOKEN'] = 'test-token'
        app = FastAPI()

        @app.get("/protected", dependencies=[Depends(require_api_token)])
        def protected():
            return {"ok": True}

        self.client = TestClient(app)

    def tearDown(self):
        os.environ.pop('TONGBU_API_TOKEN', None)

    def test_requires_token(self):
        res = self.client.get("/protected")
        self.assertEqual(res.status_code, 401)

    def test_accepts_token(self):
        res = self.client.get("/protected", headers={"Authorization": "Bearer test-token"})
        self.assertEqual(res.status_code, 200)


if __name__ == '__main__':
    unittest.main()

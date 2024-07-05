from plain.runtime import settings
from plain.test import Client, TestCase
from plain.urls import reverse


class TestTemplate(TestCase):
    def setUp(self):
        self.client = Client()

    def test_template_output(self):
        settings.DEBUG = False

        url = reverse("index")
        response = self.client.get(url)

        assert response.status_code == 200
        self.assertTemplateUsed(response, "index.html")
        self.assertContains(response, "es-module-shims.js")

        self.assertContains(response, "react@17.0.2/index.js")

    def test_template_output_dev(self):
        settings.DEBUG = True

        url = reverse("index")
        response = self.client.get(url)
        # print(response.content.decode())

        assert response.status_code == 200
        self.assertTemplateUsed(response, "index.html")
        self.assertContains(response, "es-module-shims.js")

        self.assertContains(response, "react@17.0.2/dev.index.js")

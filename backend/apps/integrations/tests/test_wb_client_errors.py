from django.test import SimpleTestCase

from apps.integrations.wb_client import WBApiError


class WbClientErrorPayloadTests(SimpleTestCase):
  def test_list_payload_preserved(self):
    payload = [{"code": "CargoWarehouseRestriction", "message": "LCL"}]
    exc = WBApiError("409", status_code=409, payload=payload)
    self.assertEqual(exc.payload, payload)

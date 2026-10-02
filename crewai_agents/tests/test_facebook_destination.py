import os
import unittest
from unittest.mock import patch

import httpx

from crewai_agents.app import marketing


class FacebookDestinationTests(unittest.TestCase):
    def setUp(self):
        marketing._facebook_destination.cache_clear()
        self.addCleanup(marketing._facebook_destination.cache_clear)
        p = patch.dict(os.environ, FACEBOOK_GRAPH_VERSION='v99.0', FACEBOOK_PAGE_ID='123',
                       FACEBOOK_PAGE_ACCESS_TOKEN='configured-user-token', PUBLISHING_ENABLED='true',
                       PUBLIC_API_BASE_URL='https://crew.example')
        p.start(); self.addCleanup(p.stop)

    def response(self, body, status=200):
        return httpx.Response(status, json=body, request=httpx.Request('GET', 'https://graph.facebook.com'))

    def test_user_token_resolves_exact_page_and_checks_read_access(self):
        responses = [self.response({'id':'user-1','name':'Owner'}),
                     self.response({'id':'123','access_token':'resolved-page-token'}),
                     self.response({'id':'123','name':'Bun2too'}), self.response({'data':[]})]
        with patch.object(marketing.httpx, 'get', side_effect=responses) as get:
            state = marketing.verify_delivery()
            again = marketing.verify_delivery()
        self.assertEqual(state['page_id'], '123')
        self.assertEqual(state, again)
        self.assertFalse(state['publishing_permission_verified'])
        self.assertEqual(get.call_count, 4)
        self.assertTrue(get.call_args_list[1].args[0].endswith('/123'))
        self.assertEqual(get.call_args_list[-1].kwargs['headers']['Authorization'], 'Bearer resolved-page-token')
        self.assertNotIn('token', str(state))

    def test_direct_page_token_does_not_exchange(self):
        with patch.object(marketing.httpx, 'get', side_effect=[self.response({'id':'123','name':'Bun2too'}),
                                                              self.response({'data':[]})]) as get:
            self.assertEqual(marketing.facebook_destination()[2], 'configured-user-token')
        self.assertEqual(get.call_count, 2)

    def test_wrong_resolved_identity_cannot_read_or_publish(self):
        responses = [self.response({'id':'user-1'}), self.response({'id':'123','access_token':'wrong-page-token'}),
                     self.response({'id':'456','name':'Another Page'})]
        with patch.object(marketing.httpx, 'get', side_effect=responses) as get, patch.object(marketing.httpx, 'post') as post:
            with self.assertRaisesRegex(ValueError, 'does not match'):
                marketing.verify_delivery()
        self.assertEqual(get.call_count, 3)
        post.assert_not_called()

    def test_denied_permissions_are_not_cached_as_success(self):
        responses = [self.response({'id':'123'}),self.response({'error':{'message':'Permission denied','code':10}},400),
                     self.response({'id':'123'}),self.response({'data':[]})]
        with patch.object(marketing.httpx, 'get', side_effect=responses) as get:
            with self.assertRaises(httpx.HTTPStatusError):
                marketing.verify_delivery()
            self.assertEqual(marketing.verify_delivery()['status'], 'ready')
        self.assertEqual(get.call_count, 4)


if __name__ == '__main__':
    unittest.main()

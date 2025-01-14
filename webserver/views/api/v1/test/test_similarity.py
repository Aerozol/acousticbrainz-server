import os
import json
import mock
import uuid

from webserver.testing import AcousticbrainzTestCase
from webserver.views.api.v1 import similarity
from webserver.views.api.exceptions import APIBadRequest
from similarity.exceptions import IndexNotFoundException, ItemNotFoundException
from webserver.testing import DB_TEST_DATA_PATH
from db.exceptions import NoDataFoundException
from webserver.views.api.v1.similarity import RemoveDupsType


class APISimilarityViewsTestCase(AcousticbrainzTestCase):

    def setUp(self):
        super(APISimilarityViewsTestCase, self).setUp()
        self.uuid = str(uuid.uuid4())

        self.test_recording1_mbid = '0dad432b-16cc-4bf0-8961-fd31d124b01b'
        self.test_recording1_data_json = open(os.path.join(DB_TEST_DATA_PATH, self.test_recording1_mbid + '.json')).read()
        self.test_recording1_data = json.loads(self.test_recording1_data_json)

        self.test_recording2_mbid = 'e8afe383-1478-497e-90b1-7885c7f37f6e'
        self.test_recording2_data_json = open(os.path.join(DB_TEST_DATA_PATH, self.test_recording2_mbid + '.json')).read()
        self.test_recording2_data = json.loads(self.test_recording2_data_json)

    @mock.patch("webserver.views.api.v1.similarity.AnnoyModel")
    def test_get_similar_recordings_bad_uuid(self, annoy_model):
        """ URL Endpoint returns 404 because url-part doesn't match UUID.
            This error is raised by Flask, but we special-case to json.
        """
        resp = self.client.get("/api/v1/similarity/mfccs/nothing")
        self.assertEqual(404, resp.status_code)

        annoy_model.assert_not_called()
        expected_result = {"message": "The requested URL was not found on the server. "
                                      "If you entered the URL manually please check your spelling and try again."}
        self.assertEqual(resp.json, expected_result)

    @mock.patch("webserver.views.api.v1.similarity.AnnoyModel")
    def test_get_similar_recordings_invalid_params(self, annoy_model):
        # If index params are not in index_model.BASE_INDICES, they default.
        # If n_neighbours is larger than 1000, it defaults.
        annoy_mock = mock.Mock()
        annoy_mock.get_bulk_nns_by_mbid.return_value = {"f2cf852b-644c-4f2b-8c17-d059ead1f675": {"0": [
            {"distance": 0.0001, "offset": 2, "recording_mbid": "f2cf852b-644c-4f2b-8c17-d059ead1f675"},
            {"distance": 0.0002, "offset": 0, "recording_mbid": "a48a4c29-082a-447b-97ea-c33d1e36b160"}
        ]}}
        annoy_model.return_value = annoy_mock
        resp = self.client.get("/api/v1/similarity/mfccs/?n_trees=-1&distance_type=7&n_neighbours=2000&recording_ids=%s:x" % self.uuid)
        self.assertEqual(200, resp.status_code)

        offset = 0
        distance_type = "angular"
        n_trees = 10
        n_neighbours = 1000
        metric = "mfccs"
        annoy_model.assert_called_with(metric, n_trees=n_trees, distance_type=distance_type, load_existing=True)
        annoy_mock.get_bulk_nns_by_mbid.assert_called_with([(self.uuid, offset)], n_neighbours)

        # If n_neighbours is not numerical, it defaults
        resp = self.client.get("/api/v1/similarity/mfccs/?n_trees=-1&distance_type=7&n_neighbours=x&recording_ids=%s" % self.uuid)
        self.assertEqual(200, resp.status_code)

        annoy_model.assert_called_with(metric, n_trees=n_trees, distance_type=distance_type, load_existing=True)
        n_neighbours = 200
        annoy_mock.get_bulk_nns_by_mbid.assert_called_with([(self.uuid, offset)], n_neighbours)

    @mock.patch("webserver.views.api.v1.similarity.AnnoyModel")
    def test_get_similar_recordings_invalid_metric(self, annoy_model):
        # If metric does not exist, APIBadRequest is raised.
        resp = self.client.get("/api/v1/similarity/nothing/?recording_ids=c5f4909e-1d7b-4f15-a6f6-1af376bc01c9")
        self.assertEqual(400, resp.status_code)
        annoy_model.assert_not_called()
        expected_result = {"message": "An index with the specified metric does not exist."}
        self.assertEqual(expected_result, resp.json)

    def test_get_many_similar_recordings_no_params(self):
        # No recording_ids parameter results in APIBadRequest.
        resp = self.client.get("/api/v1/similarity/mfccs/")
        self.assertEqual(400, resp.status_code)
        expected_result = {"message": "Missing `recording_ids` parameter"}
        self.assertEqual(resp.json, expected_result)

    @mock.patch("webserver.views.api.v1.similarity.AnnoyModel")
    def test_get_many_similar_recordings(self, annoy_model):
        # Check that similar recordings are returned for many recordings,
        # including two offsets of the same MBID.
        params = "c5f4909e-1d7b-4f15-a6f6-1af376bc01c9;7f27d7a9-27f0-4663-9d20-2c9c40200e6d:3;" \
                 "405a5ff4-7ee2-436b-95c1-90ce8a83b359:2;405a5ff4-7ee2-436b-95c1-90ce8a83b359:3"
        similars = [{'recording_mbid': "similar_rec1", 'offset': 0, 'distance': 0.1},
                    {'recording_mbid': "similar_rec2", 'offset': 0, 'distance': 0.1}]
        expected_result = {
            "c5f4909e-1d7b-4f15-a6f6-1af376bc01c9": {"0": similars},
            "7f27d7a9-27f0-4663-9d20-2c9c40200e6d": {"3": similars},
            "405a5ff4-7ee2-436b-95c1-90ce8a83b359": {"2": similars, "3": similars}
        }
        annoy_mock = mock.Mock()
        annoy_mock.get_bulk_nns_by_mbid.return_value = expected_result
        annoy_model.return_value = annoy_mock

        resp = self.client.get('api/v1/similarity/mfccs/?recording_ids=' + params)
        self.assertEqual(200, resp.status_code)
        self.assertEqual(expected_result, resp.json)

        # Index parameters should default if not specified by query string.
        annoy_model.assert_called_with("mfccs", n_trees=10, distance_type="angular", load_existing=True)

        recordings = [("c5f4909e-1d7b-4f15-a6f6-1af376bc01c9", 0),
                      ("7f27d7a9-27f0-4663-9d20-2c9c40200e6d", 3),
                      ("405a5ff4-7ee2-436b-95c1-90ce8a83b359", 2),
                      ("405a5ff4-7ee2-436b-95c1-90ce8a83b359", 3)]

        annoy_mock.get_bulk_nns_by_mbid.assert_called_with(recordings, 200)

        # upper-case
        params = "c5f4909e-1d7b-4f15-a6f6-1AF376BC01C9"
        expected_result = {
            "c5f4909e-1d7b-4f15-a6f6-1af376bc01c9": {"0": similars}
        }
        annoy_mock.get_bulk_nns_by_mbid.return_value = expected_result

        # get_bulk_nns.return_value = expected_result
        resp = self.client.get('api/v1/similarity/mfccs/?recording_ids=' + params)
        self.assertEqual(200, resp.status_code)
        self.assertEqual(resp.json, expected_result)

        # Recordings passed in should be lowercased when parsing.
        recordings = [("c5f4909e-1d7b-4f15-a6f6-1af376bc01c9", 0)]
        annoy_mock.get_bulk_nns_by_mbid.assert_called_with(recordings, 200)

    @mock.patch("webserver.views.api.v1.similarity.AnnoyModel")
    def test_get_many_similar_recordings_missing_mbid(self, annoy_model):
        # Check that within a set of mbid parameters, the ones absent
        # from the database are ignored.
        recordings = "c5f4909e-1d7b-4f15-a6f6-1af376bc01c9;7f27d7a9-27f0-4663-9d20-2c9c40200e6d:3;" \
                     "405a5ff4-7ee2-436b-95c1-90ce8a83b359:2"
        expected_result = {
            "c5f4909e-1d7b-4f15-a6f6-1af376bc01c9": {"0": [
                {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 0, 'distance': 0.5},
                {'recording_mbid': '20f6a7d7-cbd4-4609-9804-e734b3aec8c7', 'offset': 0, 'distance': 0.7}]
            },
            "405a5ff4-7ee2-436b-95c1-90ce8a83b359": {"2": [
                {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 0, 'distance': 0.5},
                {'recording_mbid': '20f6a7d7-cbd4-4609-9804-e734b3aec8c7', 'offset': 0, 'distance': 0.7}]
            }
        }
        annoy_mock = mock.Mock()
        annoy_mock.get_bulk_nns_by_mbid.return_value = expected_result
        annoy_model.return_value = annoy_mock

        query_string = {"recording_ids": recordings,
                        "n_trees": "-1",
                        "distance_type": "x",
                        "n_neighbours": "2000"}
        resp = self.client.get("/api/v1/similarity/mfccs/", query_string=query_string)
        self.assertEqual(200, resp.status_code)
        self.assertEqual(expected_result, resp.json)

        # If index parameters are invalid, they are defaulted.
        annoy_model.assert_called_with("mfccs", n_trees=10, distance_type="angular", load_existing=True)

        recordings = [("c5f4909e-1d7b-4f15-a6f6-1af376bc01c9", 0),
                      ("7f27d7a9-27f0-4663-9d20-2c9c40200e6d", 3),
                      ("405a5ff4-7ee2-436b-95c1-90ce8a83b359", 2)]
        annoy_mock.get_bulk_nns_by_mbid.assert_called_with(recordings, 1000)

    def test_get_many_similar_recordings_more_than_200(self):
        # Check that a request for over 200 recordings raises an error.
        manyids = [str(uuid.uuid4()) for i in range(26)]
        limit_exceed_url = ";".join(manyids)
        resp = self.client.get("/api/v1/similarity/mfccs/?recording_ids=" + limit_exceed_url)
        self.assertEqual(400, resp.status_code)
        expected_result = {"message": "More than 25 recordings not allowed per request"}
        self.assertEqual(expected_result, resp.json)

    @mock.patch("webserver.views.api.v1.similarity.AnnoyModel")
    def test_get_similarity_between_no_params(self, annoy_model):
        # If no index params are provided, they default.
        # Submissions can be selected using offset.
        recordings = "c5f4909e-1d7b-4f15-a6f6-1af376bc01c9;7f27d7a9-27f0-4663-9d20-2c9c40200e6d:2"
        rec_1 = ("c5f4909e-1d7b-4f15-a6f6-1af376bc01c9", 0)
        rec_2 = ("7f27d7a9-27f0-4663-9d20-2c9c40200e6d", 2)

        annoy_mock = mock.Mock()
        annoy_mock.get_similarity_between.return_value = 1
        annoy_model.return_value = annoy_mock

        resp = self.client.get("/api/v1/similarity/mfccs/between/?recording_ids=" + recordings)
        self.assertEqual(200, resp.status_code)
        self.assertEqual({"mfccs": 1}, resp.json)

        annoy_model.assert_called_with("mfccs", n_trees=10, distance_type="angular", load_existing=True)
        annoy_mock.get_similarity_between.assert_called_with(rec_1, rec_2)

    @mock.patch("webserver.views.api.v1.similarity.AnnoyModel")
    def test_get_similarity_between_exceptions(self, annoy_model):
        # If there is no submission for an (MBID, offset) combination,
        # empty dictionary is returned.
        annoy_mock = mock.Mock()
        annoy_mock.get_similarity_between.side_effect = NoDataFoundException
        annoy_model.return_value = annoy_mock

        recordings = "c5f4909e-1d7b-4f15-a6f6-1af376bc01c9;7f27d7a9-27f0-4663-9d20-2c9c40200e6d:2"
        resp = self.client.get("/api/v1/similarity/mfccs/between/?recording_ids=" + recordings)
        self.assertEqual(200, resp.status_code)

        expected_result = {}
        self.assertEqual(expected_result, resp.json)

        # If item is not yet loaded in index, returns empty dictionary.
        annoy_mock.get_similarity_between.side_effect = ItemNotFoundException
        resp = self.client.get("/api/v1/similarity/mfccs/between/?recording_ids=" + recordings)
        self.assertEqual(200, resp.status_code)
        self.assertEqual(expected_result, resp.json)

        # If index is unable to load, APIBadRequest is raised.
        annoy_model.side_effect = IndexNotFoundException
        resp = self.client.get("/api/v1/similarity/mfccs/between/?recording_ids=" + recordings)
        self.assertEqual(400, resp.status_code)

        expected_result = {"message": "Index does not exist with specified parameters."}
        self.assertEqual(expected_result, resp.json)

    def test_get_similarity_between_no_recordings(self):
        # Without recording_ids parameter, APIBadRequest is raised.
        resp = self.client.get("/api/v1/similarity/mfccs/between/")
        self.assertEqual(400, resp.status_code)
        expected_result = {"message": "Missing `recording_ids` parameter"}
        self.assertEqual(expected_result, resp.json)

        # If more or less than 2 recordings are specified, APIBadRequest is raised.
        recordings = "c5f4909e-1d7b-4f15-a6f6-1af376bc01c9"
        resp = self.client.get("/api/v1/similarity/mfccs/between/?recording_ids=" + recordings)
        self.assertEqual(400, resp.status_code)
        expected_result = {"message": "Does not contain 2 recordings in the request"}
        self.assertEqual(expected_result, resp.json)

        recordings = "c5f4909e-1d7b-4f15-a6f6-1af376bc01c9;7f27d7a9-27f0-4663-9d20-2c9c40200e6d;" \
                     "405a5ff4-7ee2-436b-95c1-90ce8a83b359"
        resp = self.client.get("/api/v1/similarity/mfccs/between/?recording_ids=" + recordings)
        self.assertEqual(400, resp.status_code)
        expected_result = {"message": "Does not contain 2 recordings in the request"}
        self.assertEqual(expected_result, resp.json)

    def test_limit_recordings_by_threshold(self):
        recordings = [
            {'recording_mbid': 'c5f4909e-1d7b-4f15-a6f6-1af376bc01c9', 'offset': 0, 'distance': 0.0},
            {'recording_mbid': 'c5f4909e-1d7b-4f15-a6f6-1af376bc01c9', 'offset': 1, 'distance': 0.5},
            {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 0, 'distance': 0.6},
            {'recording_mbid': '405a5ff4-7ee2-436b-95c1-90ce8a83b359', 'offset': 0, 'distance': 1.0}
        ]

        self.assertEqual(len(similarity._limit_recordings_by_threshold(recordings, None)), 4)
        self.assertEqual(len(similarity._limit_recordings_by_threshold(recordings, 1)), 4)
        self.assertEqual(len(similarity._limit_recordings_by_threshold(recordings, 0.5)), 2)
        self.assertEqual(len(similarity._limit_recordings_by_threshold(recordings, 0)), 1)

    def test_sort_and_remove_duplicate_submissions(self):
        recordings = [
            # Same mbid, same distance. First offset will be returned
            {'recording_mbid': 'c5f4909e-1d7b-4f15-a6f6-1af376bc01c9', 'offset': 0, 'distance': 0.1},
            {'recording_mbid': 'c5f4909e-1d7b-4f15-a6f6-1af376bc01c9', 'offset': 1, 'distance': 0.1},
            # Same mbid, but the distances are different, both will be kept if type is `samescore`
            {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 0, 'distance': 0.5},
            {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 1, 'distance': 0.6},
            # A set of mbids with the same distance interspersed with another mbid.
            # This will be resorted by mbid, then deduped so it will add 20f6... first and then
            # leave one of 405a...
            {'recording_mbid': '405a5ff4-7ee2-436b-95c1-90ce8a83b359', 'offset': 0, 'distance': 0.7},
            {'recording_mbid': '405a5ff4-7ee2-436b-95c1-90ce8a83b359', 'offset': 1, 'distance': 0.7},
            {'recording_mbid': '20f6a7d7-cbd4-4609-9804-e734b3aec8c7', 'offset': 0, 'distance': 0.7},
            {'recording_mbid': '405a5ff4-7ee2-436b-95c1-90ce8a83b359', 'offset': 2, 'distance': 0.7},
            # Same as the 2nd mbid, but with a much larger distance
            # will get left on `samescore` and `none`, but removed on `all`
            {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 1, 'distance': 0.8},
        ]

        filtered = similarity._sort_and_remove_duplicate_submissions(recordings, RemoveDupsType.samescore)
        expected = [
            {'recording_mbid': 'c5f4909e-1d7b-4f15-a6f6-1af376bc01c9', 'offset': 0, 'distance': 0.1},
            {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 0, 'distance': 0.5},
            {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 1, 'distance': 0.6},
            {'recording_mbid': '20f6a7d7-cbd4-4609-9804-e734b3aec8c7', 'offset': 0, 'distance': 0.7},
            {'recording_mbid': '405a5ff4-7ee2-436b-95c1-90ce8a83b359', 'offset': 0, 'distance': 0.7},
            {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 1, 'distance': 0.8},
        ]
        self.assertEqual(filtered, expected)

        only_sorted = similarity._sort_and_remove_duplicate_submissions(recordings, RemoveDupsType.none)
        expected = [
            {'recording_mbid': 'c5f4909e-1d7b-4f15-a6f6-1af376bc01c9', 'offset': 0, 'distance': 0.1},
            {'recording_mbid': 'c5f4909e-1d7b-4f15-a6f6-1af376bc01c9', 'offset': 1, 'distance': 0.1},
            {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 0, 'distance': 0.5},
            {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 1, 'distance': 0.6},
            {'recording_mbid': '20f6a7d7-cbd4-4609-9804-e734b3aec8c7', 'offset': 0, 'distance': 0.7},
            {'recording_mbid': '405a5ff4-7ee2-436b-95c1-90ce8a83b359', 'offset': 0, 'distance': 0.7},
            {'recording_mbid': '405a5ff4-7ee2-436b-95c1-90ce8a83b359', 'offset': 1, 'distance': 0.7},
            {'recording_mbid': '405a5ff4-7ee2-436b-95c1-90ce8a83b359', 'offset': 2, 'distance': 0.7},
            {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 1, 'distance': 0.8},
        ]
        self.assertEqual(only_sorted, expected)

        filtered = similarity._sort_and_remove_duplicate_submissions(recordings, RemoveDupsType.all)
        expected = [
            {'recording_mbid': 'c5f4909e-1d7b-4f15-a6f6-1af376bc01c9', 'offset': 0, 'distance': 0.1},
            {'recording_mbid': '7f27d7a9-27f0-4663-9d20-2c9c40200e6d', 'offset': 0, 'distance': 0.5},
            {'recording_mbid': '20f6a7d7-cbd4-4609-9804-e734b3aec8c7', 'offset': 0, 'distance': 0.7},
            {'recording_mbid': '405a5ff4-7ee2-436b-95c1-90ce8a83b359', 'offset': 0, 'distance': 0.7},
        ]
        self.assertEqual(filtered, expected)


class SimilarityValidationTest(AcousticbrainzTestCase):

    def test_check_index_params(self):
        # If metric does not exist, APIBadRequest is raised.
        metric = "x"
        with self.assertRaises(APIBadRequest) as ex:
            similarity._check_index_params(metric)
        self.assertEqual(str(ex.exception), "An index with the specified metric does not exist.")

    def test_check_index_params_neighbours(self):
        with self.app.test_request_context(query_string={'n_neighbours': '-4'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(n_neighbours, 1)
        with self.app.test_request_context(query_string={'n_neighbours': 'x'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(n_neighbours, 200)
        with self.app.test_request_context(query_string={'n_neighbours': '1400'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(n_neighbours, 1000)
        with self.app.test_request_context(query_string={'n_neighbours': '0'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(n_neighbours, 1)

    def test_check_index_params_threshold(self):
        with self.app.test_request_context(query_string={'threshold': '-4'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(threshold, 0)

        with self.app.test_request_context(query_string={'threshold': '-4'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(threshold, 0)

        with self.app.test_request_context(query_string={'threshold': '0.3'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(threshold, 0.3)

        with self.app.test_request_context(query_string={'threshold': '2'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(threshold, 1)

        with self.app.test_request_context(query_string={'threshold': 'x'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertIsNone(threshold)

    def test_check_index_params_remove_dups(self):
        with self.app.test_request_context(query_string={'remove_dups': 'all'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(remove_dups, 'all')
        with self.app.test_request_context(query_string={'remove_dups': 'Samescore'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(remove_dups, 'samescore')
        with self.app.test_request_context(query_string={}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(remove_dups, 'none')
        with self.app.test_request_context(query_string={'remove_dups': 'x'}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(remove_dups, 'none')
        with self.app.test_request_context(query_string={'remove_dups': ''}):
            metric, distance_type, n_trees, n_neighbours, threshold, remove_dups = similarity._check_index_params('mfccs')
            self.assertEqual(remove_dups, 'none')

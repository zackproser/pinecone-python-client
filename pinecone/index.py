#
# Copyright (c) 2020-2021 Pinecone Systems Inc. All right reserved.
#
from tqdm import tqdm
from collections.abc import Iterable
from typing import Union, List, Tuple, Optional, Dict, Any

from pinecone import Config
from pinecone.core.client import ApiClient
from .core.client.models import FetchResponse, ProtobufAny, QueryRequest, QueryResponse, QueryVector, RpcStatus, \
    ScoredVector, SingleQueryResults, DescribeIndexStatsResponse, UpsertRequest, UpsertResponse, UpdateRequest, \
    Vector, DeleteRequest, UpdateRequest, DescribeIndexStatsRequest
from pinecone.core.client.api.vector_operations_api import VectorOperationsApi
from pinecone.core.utils import fix_tuple_length, get_user_agent
import copy

__all__ = [
    "Index", "FetchResponse", "ProtobufAny", "QueryRequest", "QueryResponse", "QueryVector", "RpcStatus",
    "ScoredVector", "SingleQueryResults", "DescribeIndexStatsResponse", "UpsertRequest", "UpsertResponse",
    "UpdateRequest", "Vector", "DeleteRequest", "UpdateRequest", "DescribeIndexStatsRequest"
]

from .core.utils.error_handling import validate_and_convert_errors

_OPENAPI_ENDPOINT_PARAMS = (
    '_return_http_data_only', '_preload_content', '_request_timeout',
    '_check_input_type', '_check_return_type', '_host_index', 'async_req'
)


def parse_query_response(response: QueryResponse, unary_query: bool):
    if unary_query:
        response._data_store.pop('results', None)
    else:
        response._data_store.pop('matches', None)
        response._data_store.pop('namespace', None)
    return response


class Index(ApiClient):

    """
    A client for interacting with a Pinecone index via REST API.
    For improved performance, use the Pinecone GRPC index client.
    """
    def __init__(self, index_name: str, pool_threads=1):
        openapi_client_config = copy.deepcopy(Config.OPENAPI_CONFIG)
        openapi_client_config.api_key = openapi_client_config.api_key or {}
        openapi_client_config.api_key['ApiKeyAuth'] = openapi_client_config.api_key.get('ApiKeyAuth', Config.API_KEY)
        openapi_client_config.server_variables = openapi_client_config.server_variables or {}
        openapi_client_config.server_variables = {
            **{
                'environment': Config.ENVIRONMENT,
                'index_name': index_name,
                'project_name': Config.PROJECT_NAME
            },
            **openapi_client_config.server_variables
        }
        super().__init__(configuration=openapi_client_config, pool_threads=pool_threads)
        self.user_agent = get_user_agent()
        self._vector_api = VectorOperationsApi(self)

    @validate_and_convert_errors
    def upsert(self,
               vectors: Union[List[Vector], List[Tuple]],
               namespace: Optional[str] = None,
               batch_size: Optional[int] = None,
               show_progress: bool = True,
               **kwargs) -> UpsertResponse:
        """
        The upsert operation writes vectors into a namespace.
        If a new value is upserted for an existing vector id, it will overwrite the previous value.

        API reference: https://docs.pinecone.io/reference/upsert

        Examples:
            >>> index.upsert([('id1', [1.0, 2.0, 3.0], {'key': 'value'}), ('id2', [1.0, 2.0, 3.0])])
            >>> index.upsert([Vector(id='id1', values=[1.0, 2.0, 3.0], metadata={'key': 'value'}),
            >>>              Vector(id='id2', values=[1.0, 2.0, 3.0])])

        Args:
            vectors (Union[List[Vector], List[Tuple]]): A list of vectors to upsert.

                     A vector can be represented by a 1) Vector object or a 2) tuple.
                     1) if a tuple is used, it must be of the form (id, values, metadata) or (id, values).
                        where id is a string, vector is a list of floats, and metadata is a dict.
                        Examples: ('id1', [1.0, 2.0, 3.0], {'key': 'value'}), ('id2', [1.0, 2.0, 3.0])

                    2) if a Vector object is used, a Vector object must be of the form Vector(id, values, metadata),
                        where metadata is an optional argument of the type
                        Dict[str, Union[str, float, int, bool, List[int], List[float], List[str]]].
                       Examples: Vector(id='id1', values=[1.0, 2.0, 3.0], metadata={'key': 'value'}),
                                 Vector(id='id2', values=[1.0, 2.0, 3.0])

                    Note: the dimension of each vector must match the dimension of the index.

            namespace (str): The namespace to write to. If not specified, the default namespace is used. [optional]
            batch_size (int): The number of vectors to upsert in each batch.
                               If not specified, all vectors will be upserted in a single batch. [optional]
            show_progress (bool): Whether to show a progress bar using tqdm.
                                  Applied only if batch_size is provided. Defaults to True.
        Keyword Args:
            Supports OpenAPI client keyword arguments. See pinecone.core.client.models.UpsertRequest for more details.

        Returns: UpsertResponse, includes the number of vectors upserted.
        """
        _check_type = kwargs.pop('_check_type', False)

        if batch_size is None:
            return self._upsert_batch(vectors, namespace, **kwargs)

        if not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError('batch_size must be a positive integer')

        pbar = tqdm(total=len(vectors), disable=not show_progress, desc='Upserted vectors')
        total_upserted = 0
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            batch_result = self._upsert_batch(batch, namespace, **kwargs)
            total_upserted += batch_result.upserted_count
            pbar.update(len(batch))
        return UpsertResponse(upserted_count=total_upserted)

    def _upsert_batch(self,
                      vectors: List[Vector],
                      namespace: Optional[str],
                      _check_type: bool,
                      **kwargs) -> UpsertResponse:
        vectors = list(map(self._transform_upsert_vector, vectors))
        args_dict = self._parse_args_to_dict([('namespace', namespace)])

        return self._vector_api.upsert(
            UpsertRequest(
                vectors=vectors,
                **args_dict,
                _check_type=_check_type,
                **{k: v for k, v in kwargs.items() if k not in _OPENAPI_ENDPOINT_PARAMS}
            ),
            **{k: v for k, v in kwargs.items() if k in _OPENAPI_ENDPOINT_PARAMS}
        )

    @staticmethod
    def _transform_upsert_vector(item: Union[Vector, Tuple], _check_type):
        if isinstance(item, Vector):
            return item
        if isinstance(item, tuple):
            id, values, metadata = fix_tuple_length(item, 3)
            return Vector(id=id, values=values, metadata=metadata or {}, _check_type=_check_type)
        raise ValueError(f"Invalid vector value passed: cannot interpret type {type(item)}")

    @validate_and_convert_errors
    def delete(self,
               ids: Optional[List[str]] = None,
               delete_all: Optional[bool] = None,
               namespace: Optional[str] = None,
               filter: Optional[Dict[str, Union[str, float, int, bool, List, Dict]]] = None,
               **kwargs) -> Dict[str, Any]:
        """
        The Delete operation deletes vectors from the index, from a single namespace.
        No error raised if the vector id does not exist.
        Note: for any delete call, if namespace is not specified, the default namespace is used.

        Delete can occur in the following mutual exclusive ways:
        1. Delete by ids from a single namespace
        2. Delete all vectors from a single namespace by setting delete_all to True
        3. Delete all vectors from a single namespace by specifying a metadata filter
           (note that for this option delete all must be set to False)

        API reference: https://docs.pinecone.io/reference/delete_post

        Examples:
            >>> index.delete(ids=['id1', 'id2'], namespace='my_namespace')
            >>> index.delete(delete_all=True, namespace='my_namespace')
            >>> index.delete(filter={'key': 'value'}, namespace='my_namespace')

        Args:
            ids (List[str]): Vector ids to delete [optional]
            delete_all (bool): This indicates that all vectors in the index namespace should be deleted.. [optional]
                               Default is False.
            namespace (str): The namespace to delete vectors from [optional]
                             If not specified, the default namespace is used.
            filter (Dict[str, Union[str, float, int, bool, List, Dict]]):
                    If specified, the metadata filter here will be used to select the vectors to delete.
                    This is mutually exclusive with specifying ids to delete in the ids param or using delete_all=True.
                     See https://www.pinecone.io/docs/metadata-filtering/.. [optional]

      Keyword Args:
        Supports OpenAPI client keyword arguments. See pinecone.core.client.models.DeleteRequest for more details.


        Returns: An empty dictionary if the delete operation was successful.
        """
        _check_type = kwargs.pop('_check_type', False)
        args_dict = self._parse_args_to_dict([('ids', ids),
                                              ('delete_all', delete_all),
                                              ('namespace', namespace),
                                              ('filter', filter)])

        return self._vector_api.delete(
            DeleteRequest(
                **args_dict,
                **{k: v for k, v in kwargs.items() if k not in _OPENAPI_ENDPOINT_PARAMS and v is not None},
                _check_type=_check_type
            ),
            **{k: v for k, v in kwargs.items() if k in _OPENAPI_ENDPOINT_PARAMS}
        )

    @validate_and_convert_errors
    def fetch(self,
              ids: List[str],
              namespace: Optional[str] = None,
              **kwargs) -> FetchResponse:
        """
        The fetch operation looks up and returns vectors, by ID, from a single namespace.
        The returned vectors include the vector data and/or metadata.

        API reference: https://docs.pinecone.io/reference/fetch

        Examples:
            >>> index.fetch(ids=['id1', 'id2'], namespace='my_namespace')
            >>> index.fetch(ids=['id1', 'id2'])

        Args:
            ids (List[str]): The vector IDs to fetch.
            namespace (str): The namespace to fetch vectors from.
                             If not specified, the default namespace is used. [optional]
        Keyword Args:
            Supports OpenAPI client keyword arguments. See pinecone.core.client.models.FetchResponse for more details.


        Returns: FetchResponse object which contains the list of Vector objects, and namespace name.
        """
        args_dict = self._parse_args_to_dict([('namespace', namespace)])
        return self._vector_api.fetch(ids=ids, **args_dict, **kwargs)

    @validate_and_convert_errors
    def query(self,
              vector: Optional[List[float]] = None,
              id: Optional[str] = None,
              queries: Optional[Union[List[QueryVector], List[Tuple]]] = None,
              top_k: Optional[int] = None,
              namespace: Optional[str] = None,
              filter: Optional[Dict[str, Union[str, float, int, bool, List, Dict]]] = None,
              include_values: Optional[bool] = None,
              include_metadata: Optional[bool] = None,
              **kwargs) -> QueryResponse:
        """
        The Query operation searches a namespace, using a query vector.
        It retrieves the ids of the most similar items in a namespace, along with their similarity scores.

        API reference: https://docs.pinecone.io/reference/query

        Examples:
            >>> index.query(vector=[1, 2, 3], top_k=10, namespace='my_namespace')
            >>> index.query(id='id1', top_k=10, namespace='my_namespace')
            >>> index.query(vector=[1, 2, 3], top_k=10, namespace='my_namespace', filter={'key': 'value'})
            >>> index.query(id='id1', top_k=10, namespace='my_namespace', include_metadata=True, include_values=True)

        Args:
            vector (List[float]): The query vector. This should be the same length as the dimension of the index
                                  being queried. Each `query()` request can contain only one of the parameters
                                  `queries`, `id` or `vector`.. [optional]
            id (str): The unique ID of the vector to be used as a query vector.
                      Each `query()` request can contain only one of the parameters
                      `queries`, `vector`, or  `id`.. [optional]
            queries ([QueryVector]): DEPRECATED. The query vectors.
                                     Each `query()` request can contain only one of the parameters
                                     `queries`, `vector`, or  `id`.. [optional]
            top_k (int): The number of results to return for each query. Must be an integer greater than 1.
            namespace (str): The namespace to fetch vectors from.
                             If not specified, the default namespace is used. [optional]
            filter (Dict[str, Union[str, float, int, bool, List, Dict]]):
                    The filter to apply. You can use vector metadata to limit your search.
                    See https://www.pinecone.io/docs/metadata-filtering/.. [optional]
            include_values (bool): Indicates whether vector values are included in the response.
                                   If omitted the server will use the default value of False [optional]
            include_metadata (bool): Indicates whether metadata is included in the response as well as the ids.
                                     If omitted the server will use the default value of False  [optional]

        Keyword Args:
            Supports OpenAPI client keyword arguments. See pinecone.core.client.models.QueryRequest for more details.

        Returns: QueryResponse object which contains the list of the closest vectors as ScoredVector objects,
                 and namespace name.
        """
        def _query_transform(item):
            if isinstance(item, QueryVector):
                return item
            if isinstance(item, tuple):
                values, filter = fix_tuple_length(item, 2)
                if filter is None:
                    return QueryVector(values=values, _check_type=_check_type)
                else:
                    return QueryVector(values=values, filter=filter, _check_type=_check_type)
            if isinstance(item, Iterable):
                return QueryVector(values=item, _check_type=_check_type)
            raise ValueError(f"Invalid query vector value passed: cannot interpret type {type(item)}")

        _check_type = kwargs.pop('_check_type', False)
        queries = list(map(_query_transform, queries)) if queries is not None else None
        args_dict = self._parse_args_to_dict([('vector', vector),
                                              ('id', id),
                                              ('queries', queries),
                                              ('top_k', top_k),
                                              ('namespace', namespace),
                                              ('filter', filter),
                                              ('include_values', include_values),
                                              ('include_metadata', include_metadata)])

        def _query_transform(item):
            if isinstance(item, QueryVector):
                return item
            if isinstance(item, tuple):
                values, filter = fix_tuple_length(item, 2)
                return QueryVector(values=values, filter=filter, _check_type=_check_type)
            if isinstance(item, Iterable):
                return QueryVector(values=item, _check_type=_check_type)
            raise ValueError(f"Invalid query vector value passed: cannot interpret type {type(item)}")

        response = self._vector_api.query(
            QueryRequest(
                **args_dict,
                _check_type=_check_type,
                **{k: v for k, v in kwargs.items() if k not in _OPENAPI_ENDPOINT_PARAMS}
            ),
            **{k: v for k, v in kwargs.items() if k in _OPENAPI_ENDPOINT_PARAMS}
        )
        return parse_query_response(response, vector is not None or id)

    @validate_and_convert_errors
    def update(self,
               id: str,
               values: Optional[List[float]] = None,
               set_metadata: Optional[Dict[str,
                                           Union[str, float, int, bool, List[int], List[float], List[str]]]] = None,
               namespace: Optional[str] = None,
               **kwargs) -> Dict[str, Any]:
        """
        The Update operation updates vector in a namespace.
        If a value is included, it will overwrite the previous value.
        If a set_metadata is included,
        the values of the fields specified in it will be added or overwrite the previous value.

        API reference: https://docs.pinecone.io/reference/update

        Examples:
            >>> index.update(id='id1', values=[1, 2, 3], namespace='my_namespace')
            >>> index.update(id='id1', set_metadata={'key': 'value'}, namespace='my_namespace')

        Args:
            id (str): Vector's unique id.
            values (List[float]): vector values to set. [optional]
            set_metadata (Dict[str, Union[str, float, int, bool, List[int], List[float], List[str]]]]):
                metadata to set for vector. [optional]
            namespace (str): Namespace name where to update the vector.. [optional]

        Keyword Args:
            Supports OpenAPI client keyword arguments. See pinecone.core.client.models.UpdateRequest for more details.

        Returns: An empty dictionary if the update was successful.
        """
        _check_type = kwargs.pop('_check_type', False)
        args_dict = self._parse_args_to_dict([('values', values),
                                              ('set_metadata', set_metadata),
                                              ('namespace', namespace)])
        return self._vector_api.update(UpdateRequest(
                id=id,
                **args_dict,
                _check_type=_check_type,
                **{k: v for k, v in kwargs.items() if k not in _OPENAPI_ENDPOINT_PARAMS}
            ),
            **{k: v for k, v in kwargs.items() if k in _OPENAPI_ENDPOINT_PARAMS})

    @validate_and_convert_errors
    def describe_index_stats(self,
                             filter: Optional[Dict[str, Union[str, float, int, bool, List, Dict]]] = None,
                             **kwargs) -> DescribeIndexStatsResponse:
        """
        The DescribeIndexStats operation returns statistics about the index's contents.
        For example: The vector count per namespace and the number of dimensions.

        API reference: https://docs.pinecone.io/reference/describe_index_stats_post

        Examples:
            >>> index.describe_index_stats()
            >>> index.describe_index_stats(filter={'key': 'value'})

        Args:
            filter (Dict[str, Union[str, float, int, bool, List, Dict]]):
            If this parameter is present, the operation only returns statistics for vectors that satisfy the filter.
            See https://www.pinecone.io/docs/metadata-filtering/.. [optional]

        Returns: DescribeIndexStatsResponse object which contains stats about the index.
        """
        _check_type = kwargs.pop('_check_type', False)
        args_dict = self._parse_args_to_dict([('filter', filter)])

        return self._vector_api.describe_index_stats(
            DescribeIndexStatsRequest(
                **args_dict,
                **{k: v for k, v in kwargs.items() if k not in _OPENAPI_ENDPOINT_PARAMS},
                _check_type=_check_type
            ),
            **{k: v for k, v in kwargs.items() if k in _OPENAPI_ENDPOINT_PARAMS}
        )

    @staticmethod
    def _parse_args_to_dict(args: List[Tuple[str, Any]]) -> Dict[str, Any]:
        return {arg_name: val for arg_name, val in args if val is not None}

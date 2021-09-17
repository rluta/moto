from __future__ import unicode_literals

import time
from datetime import datetime
import pytz

from moto.core import BaseBackend, BaseModel
from collections import OrderedDict
from .exceptions import (
    JsonRESTError,
    DatabaseAlreadyExistsException,
    DatabaseNotFoundException,
    TableAlreadyExistsException,
    TableNotFoundException,
    PartitionAlreadyExistsException,
    PartitionNotFoundException,
    VersionNotFoundException,
)


class GlueBackend(BaseBackend):
    def __init__(self):
        self.databases = OrderedDict()

    def create_database(self, database_name, database_input):
        if database_name in self.databases:
            raise DatabaseAlreadyExistsException()

        database = FakeDatabase(database_name, database_input)
        self.databases[database_name] = database
        return database

    def get_database(self, database_name):
        try:
            return self.databases[database_name]
        except KeyError:
            raise DatabaseNotFoundException(database_name)

    def get_databases(self):
        return [self.databases[key] for key in self.databases] if self.databases else []

    def create_table(self, database_name, table_name, table_input):
        database = self.get_database(database_name)

        if table_name in database.tables:
            raise TableAlreadyExistsException()

        table = FakeTable(database_name, table_name, table_input)
        database.tables[table_name] = table
        return table

    def get_table(self, database_name, table_name):
        database = self.get_database(database_name)
        try:
            return database.tables[table_name]
        except KeyError:
            raise TableNotFoundException(table_name)

    def get_tables(self, database_name):
        database = self.get_database(database_name)
        return [table for table_name, table in database.tables.items()]

    def delete_table(self, database_name, table_name):
        database = self.get_database(database_name)
        try:
            del database.tables[table_name]
        except KeyError:
            raise TableNotFoundException(table_name)
        return {}

    def get_user_defined_functions(self, pattern):
        return []

class FakeDatabase(BaseModel):
    def __init__(self, database_name, database_input):
        self.name = database_name
        self.input = database_input
        self.created_time = datetime.utcnow().replace(tzinfo=pytz.utc)
        self.tables = OrderedDict()

    def as_dict(self):
        return {
            "Name": self.name,
            "Description": self.input.get("Description"),
            "LocationUri": self.input.get("LocationUri"),
            "Parameters": self.input.get("Parameters"),
            "CreateTime": self.created_time.isoformat(),
            "CreateTableDefaultPermissions": self.input.get(
                "CreateTableDefaultPermissions"
            ),
            "TargetDatabase": self.input.get("TargetDatabase"),
            "CatalogId": self.input.get("CatalogId"),
        }


class FakeTable(BaseModel):
    def __init__(self, database_name, table_name, table_input):
        self.database_name = database_name
        self.name = table_name
        self.partitions = OrderedDict()
        self.versions = []
        self.create_time = datetime.utcnow().replace(tzinfo=pytz.utc).isoformat()
        self.update(table_input)

    def update(self, table_input):
        table_info = dict(table_input)
        table_info['StorageDescriptor'] = FakeStorageDescriptor(table_input['StorageDescriptor']).as_dict()
        if 'UpdateTime' not in table_info:
            table_info['UpdateTime'] = datetime.utcnow().replace(tzinfo=pytz.utc).isoformat()
        self.versions.append(table_info)

    def get_version(self, ver):
        try:
            if not isinstance(ver, int):
                # "1" goes to [0]
                ver = int(ver) - 1
        except ValueError as e:
            raise JsonRESTError("InvalidInputException", str(e))

        try:
            return self.versions[ver]
        except IndexError:
            raise VersionNotFoundException()

    def as_dict(self, version=-1):
        obj = {"DatabaseName": self.database_name,
               "Name": self.name,
               "Retention": 0,
               "CreateTime": self.create_time,
               "LastAccessTime": datetime.utcnow().replace(tzinfo=pytz.utc).isoformat()
               }
        obj.update(self.get_version(version))
        return obj

    def create_partition(self, partiton_input):
        partition = FakePartition(self.database_name, self.name, partiton_input)
        key = str(partition.values)
        if key in self.partitions:
            raise PartitionAlreadyExistsException()
        self.partitions[str(partition.values)] = partition

    def get_partitions(self):
        return [p for str_part_values, p in self.partitions.items()]

    def get_partition(self, values):
        try:
            return self.partitions[str(values)]
        except KeyError:
            raise PartitionNotFoundException()

    def update_partition(self, old_values, partiton_input):
        partition = FakePartition(self.database_name, self.name, partiton_input)
        key = str(partition.values)
        if old_values == partiton_input["Values"]:
            # Altering a partition in place. Don't remove it so the order of
            # returned partitions doesn't change
            if key not in self.partitions:
                raise PartitionNotFoundException()
        else:
            removed = self.partitions.pop(str(old_values), None)
            if removed is None:
                raise PartitionNotFoundException()
            if key in self.partitions:
                # Trying to update to overwrite a partition that exists
                raise PartitionAlreadyExistsException()
        self.partitions[key] = partition

    def delete_partition(self, values):
        try:
            del self.partitions[str(values)]
        except KeyError:
            raise PartitionNotFoundException()


class FakePartition(BaseModel):
    def __init__(self, database_name, table_name, partiton_input):
        self.creation_time = time.time()
        self.database_name = database_name
        self.table_name = table_name
        self.partition_input = partiton_input
        self.values = self.partition_input.get("Values", [])

    def as_dict(self):
        obj = {
            "DatabaseName": self.database_name,
            "TableName": self.table_name,
            "CreationTime": self.creation_time,
        }
        obj.update(self.partition_input)
        return obj


class FakeStorageDescriptor(BaseModel):
    compressed: bool = False
    number_of_buckets: int = 0
    serde_info: dict = {}
    bucket_columns: list = []
    sort_columns: list = []
    parameters: dict = {}
    stored_as_sub_directories: bool = False

    def __init__(self, storage_input):
        self.storage_input = storage_input

    def as_dict(self):
        obj = {
            "Compressed": self.compressed,
            "NumberOfBuckets": self.number_of_buckets,
            "BucketColumns": self.bucket_columns,
            "SortColumns": self.sort_columns,
            "Parameters": {},
            "StoredAsSubDirectories": self.stored_as_sub_directories
        }
        obj.update(self.storage_input)
        return obj


glue_backend = GlueBackend()

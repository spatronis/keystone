# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""SQL backends for the various services."""

import sqlalchemy as sql
import sqlalchemy.engine.url
from sqlalchemy.exc import DisconnectionError
from sqlalchemy.ext import declarative
import sqlalchemy.orm
import sqlalchemy.pool
from sqlalchemy import types as sql_types

from keystone.common import logging
from keystone import config
from keystone.openstack.common import jsonutils


CONF = config.CONF


ModelBase = declarative.declarative_base()


# For exporting to other modules
Column = sql.Column
String = sql.String
ForeignKey = sql.ForeignKey
DateTime = sql.DateTime
IntegrityError = sql.exc.IntegrityError
Boolean = sql.Boolean


# Special Fields
class JsonBlob(sql_types.TypeDecorator):

    impl = sql.Text

    def process_bind_param(self, value, dialect):
        return jsonutils.dumps(value)

    def process_result_value(self, value, dialect):
        return jsonutils.loads(value)


class DictBase(object):

    def to_dict(self):
        return dict(self.iteritems())

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __iter__(self):
        self._i = iter(sqlalchemy.orm.object_mapper(self).columns)
        return self

    def next(self):
        n = self._i.next().name
        return n

    def update(self, values):
        """Make the model object behave like a dict."""
        for k, v in values.iteritems():
            setattr(self, k, v)

    def iteritems(self):
        """Make the model object behave like a dict.

        Includes attributes from joins.

        """
        return dict([(k, getattr(self, k)) for k in self])
        #local = dict(self)
        #joined = dict([(k, v) for k, v in self.__dict__.iteritems()
        #               if not k[0] == '_'])
        #local.update(joined)
        #return local.iteritems()


class MySQLPingListener(object):

    """
    Ensures that MySQL connections checked out of the
    pool are alive.

    Borrowed from:
    http://groups.google.com/group/sqlalchemy/msg/a4ce563d802c929f

    Error codes caught:
    * 2006 MySQL server has gone away
    * 2013 Lost connection to MySQL server during query
    * 2014 Commands out of sync; you can't run this command now
    * 2045 Can't open shared memory; no answer from server (%lu)
    * 2055 Lost connection to MySQL server at '%s', system error: %d

    from http://dev.mysql.com/doc/refman/5.6/en/error-messages-client.html
    """

    def checkout(self, dbapi_con, con_record, con_proxy):
        try:
            dbapi_con.cursor().execute('select 1')
        except dbapi_con.OperationalError, ex:
            if ex.args[0] in (2006, 2013, 2014, 2045, 2055):
                logging.warn('Got mysql server has gone away: %s', ex)
                raise DisconnectionError("Database server went away")
            else:
                raise


# Backends
class Base(object):
    _engine = None
    _sessionmaker = None

    def get_session(self, autocommit=True, expire_on_commit=False):
        """Return a SQLAlchemy session."""
        self._engine = self._engine or self.get_engine()
        self._sessionmaker = self._sessionmaker or self.get_sessionmaker(
            self._engine)
        return self._sessionmaker()

    def get_engine(self):
        """Return a SQLAlchemy engine."""
        connection_dict = sql.engine.url.make_url(CONF.sql.connection)

        engine_config = {
            'convert_unicode': True,
            'echo': CONF.debug and CONF.verbose,
            'pool_recycle': CONF.sql.idle_timeout,
        }

        if 'sqlite' in connection_dict.drivername:
            engine_config['poolclass'] = sqlalchemy.pool.StaticPool
        elif 'mysql' in connection_dict.drivername:
            engine_config['listeners'] = [MySQLPingListener()]

        return sql.create_engine(CONF.sql.connection, **engine_config)

    def get_sessionmaker(self, engine, autocommit=True,
                         expire_on_commit=False):
        """Return a SQLAlchemy sessionmaker using the given engine."""
        return sqlalchemy.orm.sessionmaker(
            bind=engine,
            autocommit=autocommit,
            expire_on_commit=expire_on_commit)

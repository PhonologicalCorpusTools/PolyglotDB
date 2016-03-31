import os
import re
import sys
import shutil
import pickle
import logging
import time
from collections import defaultdict

import sqlalchemy
import py2neo

from py2neo import Graph
from py2neo.packages.httpstream import http
http.socket_timeout = 999

from sqlalchemy import create_engine
from ..sql.models import Base, Discourse, Speaker
from ..sql.config import Session
from ..sql.query import Lexicon, Inventory

from ..config import CorpusConfig

from ..structure import Hierarchy

from ..graph.attributes import AnnotationAttribute, PauseAnnotation

from ..graph.query import GraphQuery, SpeakerGraphQuery, DiscourseGraphQuery

from ..exceptions import (CorpusConfigError, GraphQueryError,
        ConnectionError, AuthorizationError, TemporaryConnectionError,
        NetworkAddressError, NoSoundFileError)


class BaseContext(object):
    """
    Base CorpusContext class.  Inherit from this and extend to create
    more functionality.

    Parameters
    ----------
    args : arguments or :class:`polyglotdb.config.CorpusConfig`
        If the first argument is not a CorpusConfig object, it is
        the name of the corpus
    kwargs : keyword arguments
        If a :class:`polyglotdb.config.CorpusConfig` object is not specified, all arguments and
        keyword arguments are passed to a CorpusConfig object
    """
    def __init__(self, *args, **kwargs):
        if len(args) == 0:
            raise(CorpusConfigError('Need to specify a corpus name or CorpusConfig.'))
        if isinstance(args[0], CorpusConfig):
            self.config = args[0]
        else:
            self.config = CorpusConfig(*args, **kwargs)
        self.config.init()
        self.graph = Graph(self.config.graph_connection_string)
        self.corpus_name = self.config.corpus_name
        if self.corpus_name:
            self.init_sql()

        self.hierarchy = Hierarchy({})

        self.lexicon = Lexicon(self)

        self.inventory = Inventory(self)

        self._has_sound_files = None
        self._has_all_sound_files = None
        if getattr(sys, 'frozen', False):
            self.config.reaper_path = os.path.join(sys.path[-1],'reaper')
        else:
            self.config.reaper_path = shutil.which('reaper')

        self.config.query_behavior = 'speaker'

    def load_variables(self):
        try:
            with open(os.path.join(self.config.data_dir, 'variables'), 'rb') as f:
                var = pickle.load(f)
            self.hierarchy = var['hierarchy']
        except FileNotFoundError:
            if self.corpus_name:
                self.hierarchy = self.generate_hierarchy()
                self.save_variables()

    def save_variables(self):
        with open(os.path.join(self.config.data_dir, 'variables'), 'wb') as f:
            pickle.dump({'hierarchy': self.hierarchy}, f)

    def init_sql(self):
        self.engine = create_engine(self.config.sql_connection_string)
        Session.configure(bind=self.engine)
        if not os.path.exists(self.config.db_path):
            Base.metadata.create_all(self.engine)

    def execute_cypher(self, statement, **parameters):
        try:
            return self.graph.cypher.execute(statement, **parameters)
        except http.SocketError:
            raise(ConnectionError('PolyglotDB could not connect to the server specified.'))
        except py2neo.error.Unauthorized:
            raise(AuthorizationError('The specified user and password were not authorized by the server.'))
        except http.NetworkAddressError:
            raise(NetworkAddressError('The server specified could not be found.  Please double check the server address for typos or check your internet connection.'))
        except (py2neo.cypher.TransientError,
                #py2neo.cypher.error.network.UnknownFailure,
                #py2neo.cypher.error.statement.ExternalResourceFailure
                ):
            raise(TemporaryConnectionError('The server is (likely) temporarily unavailable.'))
        except Exception:
            raise

    @property
    def discourses(self):
        '''
        Return a list of all discourses in the corpus.
        '''
        q = self.sql_session.query(Discourse).all()
        if not len(q):
            res = self.execute_cypher('''MATCH (d:Discourse:{corpus_name}) RETURN d.name as discourse'''.format(corpus_name = self.corpus_name))
            discourses = []
            for d in res:
                instance = Discourse(name = d.discourse)
                self.sql_session.add(instance)
                discourses.append(d.discourse)
            self.sql_session.flush()
            return discourses
        return [x.name for x in q]

    @property
    def speakers(self):
        q = self.sql_session.query(Speaker).all()
        if not len(q):
            res = self.execute_cypher('''MATCH (s:Speaker:{corpus_name}) RETURN s.name as speaker'''.format(corpus_name = self.corpus_name))
            speakers = []
            for s in res:
                instance = Speaker(name = s.speaker)
                self.sql_session.add(instance)
                speakers.append(s.speaker)
            self.sql_session.flush()
            return speakers
        return [x.name for x in q]

    def __enter__(self):
        self.sql_session = Session()
        self.load_variables()
        #if self.corpus_name:
        #    self.hierarchy = self.generate_hierarchy()
        return self

    def __exit__(self, exc_type, exc, exc_tb):
        if exc_type is None:
            #try:
            #    shutil.rmtree(self.config.temp_dir)
            #except:
            #    pass
            self.sql_session.commit()
            return True
        else:
            self.sql_session.rollback()
        self.sql_session.expunge_all()
        self.sql_session.close()

    def __getattr__(self, key):
        if key == 'pause':
            return PauseAnnotation(corpus = self.corpus_name)
        if key + 's' in self.hierarchy.annotation_types:
            key += 's' # FIXME
        if key in self.hierarchy.annotation_types:
            return AnnotationAttribute(key, corpus = self.corpus_name, hierarchy = self.hierarchy)
        raise(GraphQueryError('The graph does not have any annotations of type \'{}\'.  Possible types are: {}'.format(key, ', '.join(sorted(self.hierarchy.annotation_types)))))

    @property
    def word_name(self):
        for at in self.hierarchy.annotation_types:
            if at.startswith('word'): #FIXME need a better way for storing word name
                return at

    def reset_graph(self):
        '''
        Remove all nodes and relationships in the graph that are apart
        of this corpus.
        '''

        self.execute_cypher('''MATCH (n:%s) DETACH DELETE n''' % (self.corpus_name))
        self.reset_hierarchy()
        self.hierarchy = Hierarchy({})

    def reset(self):
        '''
        Reset the graph and SQL databases for a corpus.
        '''
        self.reset_graph()
        try:
            Base.metadata.drop_all(self.engine)
        except sqlalchemy.exc.OperationalError:
            pass
        Base.metadata.create_all(self.engine)

    def query_graph(self, annotation_type):
        '''
        Return a :class:`polyglotdb.config.GraphQuery` for the specified annotation type.

        When extending :class:`polyglotdb.config.GraphQuery` functionality, this function must be
        overwritten.

        Parameters
        ----------
        annotation_type : str
            The type of annotation to look for in the corpus
        '''
        if annotation_type.type not in self.hierarchy.annotation_types \
                and annotation_type.type != 'pause': #FIXME make more general
            raise(GraphQueryError('The graph does not have any annotations of type \'{}\'.  Possible types are: {}'.format(annotation_type.name, ', '.join(sorted(self.hierarchy.annotation_types)))))
        if self.config.query_behavior == 'speaker':
            cls = SpeakerGraphQuery
        elif self.config.query_behavior == 'discourse':
            cls = DiscourseGraphQuery
        else:
            cls = GraphQuery
        return cls(self, annotation_type)

    @property
    def annotation_types(self):
        return self.hierarchy.annotation_types

    @property
    def lowest_annotation(self):
        '''
        Returns the annotation type that is the lowest in the hierarchy
        of containment.
        '''
        return self.hierarchy.lowest

    def remove_discourse(self, name):
        '''
        Remove the nodes and relationships associated with a single
        discourse in the corpus.

        Parameters
        ----------
        name : str
            Name of the discourse to remove
        '''
        self.execute_cypher('''MATCH (n:%s:%s)-[r]->() DELETE n, r'''
                                    % (self.corpus_name, name))

    def discourse(self, name, annotations = None):
        '''
        Get all words spoken in a discourse.

        Parameters
        ----------
        name : str
            Name of the discourse
        '''
        w = getattr(self, 'word') #FIXME make more general
        q = self.query_graph(w).filter(w.discourse.name == name)
        q = q.order_by(w.begin)
        return q.all()

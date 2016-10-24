import math
from polyglotdb.graph.func import *
from polyglotdb.exceptions import GraphQueryError

class SummarizedContext(object):


    def get_measure(self, data_name, statistic, annotation_type, by_speaker = False, speaker = None):
        """
        abstract function to get statistic for the data_name of an annotation_type


        Parameters
        ----------
        data_name : str
            the aspect to summarize (duration, pitch, formants, etc)
        statistic : str
            how to summarize (mean, stdev, median, etc)
        annotation_type : str
            the annotation to summarize
        by_speaker : boolean
            whether to summarize by speaker or not
        speaker : str
            the specific speaker to encode baseline duration for (only for baseline duration)

        """
        baseline = False
        column = statistic +"_" + data_name
        print(statistic)
        percent = ""
        if data_name == "duration":
            num_prop = "p.end - p.begin"
        m = ""
        if statistic == "mean":
            m = "avg"
        elif statistic == "stdev": 
            m = statistic
        elif statistic == 'median':
            m = 'percentileDisc'
            percent = ", .5"
        elif statistic == "baseline":
            baseline = True
            result = self.baseline_duration(annotation_type, speaker)
        else:
            raise(AttributeError("The statistic {} is not a valid option. Options are mean, median, stdev, or baseline".format(statistic)))



        if not self.hierarchy.has_type_property('utterance','label'):
            self.encode_utterances()
        if speaker is not None:
            statement = "MATCH (p:{annotation_type}:{corpus_name})-[:spoken_by]->(s:Speaker:{corpus_name}) " \
                        "where s.name = '{speaker}' " \
                        "RETURN p.label as {annotation_type}, {measure}({num_prop}{percent}) as {column}".format(
                corpus_name = self.corpus_name, annotation_type = annotation_type, measure= m,num_prop = num_prop, percent = percent, speaker = speaker, column = column)
        if by_speaker:
            statement = "MATCH (p:{annotation_type}:{corpus_name})-[:spoken_by]->(s:Speaker:{corpus_name}) " \
                        "RETURN s.name as speaker, p.label as {annotation_type}, {measure}({num_prop}{percent}) as {column}".format(
                corpus_name = self.corpus_name, annotation_type = annotation_type, measure= m,num_prop = num_prop ,percent = percent, column = column)
        else:
            statement = "MATCH (p:{annotation_type}:{corpus_name}) RETURN p.label as {annotation_type}, {measure}({num_prop}{percent}) as {column}".format(
                corpus_name = self.corpus_name, annotation_type = annotation_type, measure= m,num_prop = num_prop, percent = percent, column = column)

        if not baseline:
            result = []
            res = self.execute_cypher(statement)
            for item in res:
                result.append(item)

        return result


    def baseline_duration(self, annotation, speaker = None):
        """
        Get the baseline duration of each word in corpus.
        Baseline duration is determined by summing the average durations of constituent phones for a word.
        If there is no underlying transcription available, the longest duration is considered the baseline.

        Parameters
        ----------
        speaker : str
            a speaker name, if desired (defaults to None)
        Returns
        -------
        word_totals : dict
            a dictionary of words and baseline durations
        """
        
        index = 'label'
        word = getattr(self, self.word_name)
        phone = getattr(self,self.phone_name)
        # if annotation == 'word':
        #     annotation = word
        if annotation == 'utterance':
            ## TODO: find a good key for utterances (labels too long anyway and are None)
            index = 'id'
            if not self.hierarchy.has_type_property('utterance','label'):
                raise(AttributeError('Annotation type \'{}\' not found.'.format(annotation)))
        if annotation == 'syllable':
            if not self.hierarchy.has_type_property('syllable','label'):
                raise(AttributeError('Annotation type \'{}\' not found.'.format(annotation)))

        speaker_statement = '''
MATCH (m:phone:{corpus_name})-[:spoken_by]->(s:Speaker:{corpus_name}) where s.name = '{speaker}'
with m.{index} as target, avg(m.end-m.begin) as dur 
with target,dur match (p:phone:{corpus_name}) 
where p.{index} = target set p.average_duration = dur 
with p as phone  match(n:{higher_annotation}:{corpus_name}) where phone.begin>=n.begin and phone.end<=n.end
with n,phone with n, n.{index} as target, sum(phone.average_duration) as baseline 
set n.baseline_duration = baseline return n.{index}, n.baseline_duration'''.format(higher_annotation=annotation,\
 corpus_name=self.corpus_name, index = index, speaker = speaker)
        
        statement = '''
MATCH (m:phone:{corpus_name})
with m.{index} as target, avg(m.end-m.begin) as dur 
with target,dur match (p:phone:{corpus_name}) 
where p.{index} = target set p.average_duration = dur 
with p as phone  match(n:{higher_annotation}:{corpus_name}) where phone.begin>=n.begin and phone.end<=n.end
with n,phone with n, n.{index} as target, sum(phone.average_duration) as baseline 
set n.baseline_duration = baseline return n.{index}, n.baseline_duration'''.format(higher_annotation=annotation,\
 corpus_name=self.corpus_name, index = index)
        if speaker is not None:
            statement=speaker_statement
        

        res = self.execute_cypher(statement)     
        result = {}
        for c in res:
            result.update({c[0]:c[1]})

        print(result)
        return result

 
    #SPEAKER

    def average_speech_rate(self):
        """
        Get the average speech rate for each speaker in a corpus

        Returns
        -------
        result: list
            the average speech rate by speaker
        """
        if not 'utterance' in self.annotation_types:
            raise(GraphQueryError('Utterances must be encodes to calculate average speech rate.'))
        if not 'syllable' in self.annotation_types:
            raise(GraphQueryError('Syllables must be encodes to calculate average speech rate.'))
        word = getattr(self, self.word_name)
        q = self.query_graph(self.utterance)


        return q.group_by(self.utterance.speaker.name.column_name('name')).aggregate(Average(self.utterance.syllable.rate))

    def make_dict(self, data, speaker = False, label = None):
        """
        turn data results into a dictionary for encoding

        Parameters
        ----------

        data : list
            a list returned by cypher

        Returns
        -------
        finaldict : dict
            a dictionary in the format for enrichment

        """
        finalDict = {}
        if not speaker:
            if type(data) == list and len(data[0])==2:
                for i,r in enumerate(data):
                    finalDict.update({r[0]:{str(data[1].keys()[1]):r[1]}})
            else:
                for r in data.keys():
                    finalDict.update({r : {'baseline_duration': data[r]}})

        if speaker:
            keys = data[0].keys()
            speaker = data[0].values()[0]
            prop = keys[2]
            firstDict = {x[label]:x[prop] for x in data  }
            speakerDict = self.make_speaker_annotations_dict(firstDict, speaker, prop)
            return speakerDict
        return finalDict


    # def encode_measure(self, data_name, statistic, annotation_type, by_speaker = False, speaker = None):
    #
    #     """
    #     encode the data into the graph
    #
    #     Parameters
    #     ----------
    #     data_name : str
    #         the aspect to summarize (duration, pitch, formants, etc)
    #     statistic : str
    #         how to summarize (mean, stdev, median, etc)
    #     annotation_type : str
    #         the annotation to summarize
    #     by_speaker : boolean
    #         whether to summarize by speaker or not
    #     speaker : str
    #         the specific speaker to encode baseline duration for (only for baseline duration)
    #     """
    #
    #
    #     res = self.get_measure(data_name, statistic, annotation_type, by_speaker, speaker)
    #
    #     dataDict = self.make_dict(res,by_speaker,annotation_type)
    #     if not by_speaker:
    #         if annotation_type == 'utterance':
    #             self.enrich_utterances(dataDict)
    #         elif annotation_type == 'word':
    #             self.enrich_lexicon(dataDict)
    #         elif annotation_type == 'phone':
    #             self.enrich_features(dataDict)
    #         elif annotation_type == 'syllable':
    #             self.enrich_syllables(dataDict)
    #     elif by_speaker:
    #         self.enrich_speaker_annotations(dataDict)

    def encode_measure(self, property_name, statistic, annotation_type, by_speaker = False):
        if property_name == 'duration':
            property = 'a.end - a.begin'
        else:
            property = 'a.{}'.format(property_name)
        if statistic.lower() in ['mean', 'average','avg']:
            func = 'avg'
            name = 'mean'
        elif statistic.lower() in ['sd','stdev']:
            func = 'stdev'
            name = 'sd'
        if by_speaker:
            statement = '''MATCH (a_type:{annotation_type}_type:{corpus_name})<-[:is_a]-(a:{annotation_type}:{corpus_name})-[:spoken_by]->(s:Speaker:{corpus_name})
            with a_type, s, {func}({property}) as value
            MERGE (a_type)-[r:spoken_by]->(s)
            with r, value
            set r.{func_name}_{property_name} = value'''
        else:
            statement = '''MATCH (a_type:{annotation_type}_type:{corpus_name})<-[:is_a]-(a:{annotation_type}:{corpus_name})
            with a_type, {func}({property}) as value
            set a_type.{func_name}_{property_name} = value
            '''
        self.execute_cypher(statement.format(corpus_name = self.corpus_name, annotation_type = annotation_type, property = property,
                        func_name = name, func = func, property_name = property_name))
        self.hierarchy.add_type_properties(self, annotation_type, [('_'.join([name, property_name]), float)])

        self.encode_hierarchy()


    def encode_baseline_duration(self, annotation_type, by_speaker = False):
        if by_speaker:
            exists_statement = '''MATCH (a_type:{annotation_type}_type:{corpus_name})-[:spoken_by]->(s:Speaker:{corpus_name})
                            RETURN 1 LIMIT 1'''.format(annotation_type = annotation_type, corpus_name = self.corpus_name)
            if len(list(self.execute_cypher(exists_statement))) == 0:
                self.encode_measure('duration','mean','phone',by_speaker)
            statement = '''MATCH (a:{annotation_type}:{corpus_name})-[:spoken_by]->(s:Speaker:{corpus_name})
            with a, s
            MATCH (a)<-[:contained_by*]-(p:{phone_name}:{corpus_name})-[:is_a]->(pt:{phone_name}_type:{corpus_name})-[r:spoken_by]->(s)
            WITH a, sum(r.mean_duration) as baseline_duration
            SET a.baseline_duration_by_speaker = baseline_duration'''.format(corpus_name = self.corpus_name, phone_name = self.phone_name,
                                                                             annotation_type = annotation_type)
            self.execute_cypher(statement)
            self.hierarchy.add_token_properties(self, annotation_type, [('baseline_duration_by_speaker', float)])
        else:
            if not self.hierarchy.has_type_property('phone', 'mean_duration'):
                self.encode_measure('duration','mean','phone',by_speaker)
            statement = '''MATCH (a:{annotation_type}:{corpus_name})
            with a
            MATCH (a)<-[:contained_by*]-(p:{phone_name}:{corpus_name})-[:is_a]->(pt:{phone_name}_type:{corpus_name})
            WITH a, sum(pt.mean_duration) as baseline_duration
            SET a.baseline_duration = baseline_duration'''.format(corpus_name = self.corpus_name, phone_name = self.phone_name,
                                                                             annotation_type = annotation_type)
            self.execute_cypher(statement)
            self.hierarchy.add_token_properties(self, annotation_type, [('baseline_duration', float)])


from uuid import uuid1

from .featured import FeaturedContext

from ..io.importer import (syllables_data_to_csvs, import_syllable_csv,
                            nonsyls_data_to_csvs, import_nonsyl_csv)

from ..io.helper import make_type_id

from ..syllabification.probabilistic import norm_count_dict, split_nonsyllabic_prob, split_ons_coda_prob
from ..syllabification.maxonset import split_nonsyllabic_maxonset, split_ons_coda_maxonset

class SyllabicContext(FeaturedContext):
    def find_onsets(self):
        statement = '''match (w:{word_name}:{corpus_name})
where (w)<-[:contained_by*]-()-[:is_a]->(:syllabic)
with w
match (n:{phone_name}:{corpus_name})-[:is_a]->(t:{corpus_name}:syllabic),
(n)-[:contained_by*]->(w)
with w, n
order by n.begin
with w,collect(n)[0..1] as coll unwind coll as n

MATCH (pn:{phone_name}:{corpus_name})-[:contained_by*]->(w)
where not (pn)<-[:precedes]-()-[:contained_by*]->(w)
with w, n,pn
match p = shortestPath((pn)-[:precedes*0..10]->(n))
with extract(x in nodes(p)[0..-1]|x.label) as onset
return onset, count(onset) as freq'''.format(corpus_name = self.corpus_name,
                                            word_name = self.word_name,
                                            phone_name = self.phone_name)
        res = self.execute_cypher(statement)
        data = {}
        for r in res:
            data[tuple(r.onset)] = r.freq
        return data

    def find_codas(self):
        statement = '''match (w:{word_name}:{corpus_name})
where (w)<-[:contained_by*]-()-[:is_a]->(:syllabic)
with w
match (n:{phone_name}:{corpus_name})-[:is_a]->(t:{corpus_name}:syllabic),
(n)-[:contained_by*]->(w)
with w, n
order by n.begin DESC
with w,collect(n)[0..1] as coll unwind coll as n

MATCH (pn:{phone_name}:{corpus_name})-[:contained_by*]->(w)
where not (pn)-[:precedes]->()-[:contained_by*]->(w)
with w, n,pn
match p = shortestPath((n)-[:precedes*0..10]->(pn))
with extract(x in nodes(p)[1..]|x.label) as coda
return coda, count(coda) as freq'''.format(corpus_name = self.corpus_name,
                                            word_name = self.word_name,
                                            phone_name = self.phone_name)

        res = self.execute_cypher(statement)
        data = {}
        for r in res:
            data[tuple(r.coda)] = r.freq
        return data

    def encode_syllabic_segments(self, phones):
        self.encode_class(phones, 'syllabic')

    def encode_number_of_syllables(self):
        pass

    def reset_syllables(self, call_back = None, stop_check = None):
        if call_back is not None:
            call_back('Resetting syllables...')
            number = self.execute_cypher('''MATCH (n:syllable:%s) return count(*) as number ''' % (self.corpus_name)).one
            call_back(0, number)
        statement = '''MATCH (p:{phone_name}:{corpus})-[r1:contained_by]->(s:syllable:{corpus})-[r4:is_a]->(st:syllable_type:{corpus}),
                (s)-[r2:contained_by]->(w:{word_name}:{corpus})
                with p,s,r1,st,r4,r2,w
                LIMIT 2000
                OPTIONAL MATCH
                (s)-[r3:precedes]->()
                DELETE r1, r2, r3, r4
                WITH p, s, w, st
                CREATE (p)-[:contained_by]->(w)
                with p, s, st
                DETACH DELETE s, st
                with p,s
                REMOVE p:onset, p:nucleus, p:coda, p.syllable_position
                RETURN count(s) as deleted_count'''.format(corpus = self.corpus_name,
                        word_name = self.word_name,
                        phone_name = self.phone_name)
        num_deleted = 0
        deleted = 1000
        while deleted > 0:
            if stop_check is not None and stop_check():
                break
            deleted = self.execute_cypher(statement).one
            num_deleted += deleted
            if call_back is not None:
                call_back(num_deleted)
        try:
            self.hierarchy.annotation_types.remove('syllable')
            self.hierarchy[self.phone_name] = self.hierarchy['syllable']
            self.hierarchy.remove_token_labels(self, 'phone', ['onset','coda','nucleus'])
            self.hierarchy.remove_token_properties(self, 'phone', ['syllable_position'])
            del self.hierarchy['syllable']
            self.encode_hierarchy()
            self.refresh_hierarchy()
        except KeyError:
            pass

    def encode_syllables(self, algorithm = 'probabilistic', call_back = None, stop_check = None):
        self.reset_syllables(call_back, stop_check)
        onsets = self.find_onsets()
        if algorithm == 'probabilistic':
            onsets = norm_count_dict(onsets, onset = True)
            codas = self.find_codas()
            codas = norm_count_dict(codas, onset = False)
        elif algorithm == 'maxonset':
            onsets = set(onsets.keys())
        else:
            raise(NotImplementedError)

        statement = '''MATCH (n:{}:syllabic) return n.label as label'''.format(self.corpus_name)
        res = self.execute_cypher(statement)
        syllabics = set(x.label for x in res)

        word_type = getattr(self, self.word_name)
        phone_type = getattr(word_type, self.phone_name)

        splits = self.discourses
        process_string = 'Processing discourse {} of {} ({})...'
        if call_back is not None:
            call_back(0, len(splits))

        self.hierarchy[self.phone_name] = 'syllable'
        self.hierarchy['syllable'] = self.word_name
        self.hierarchy.add_token_labels(self, 'phone', ['onset','coda','nucleus'])
        self.hierarchy.add_token_properties(self, 'phone', [('syllable_position', str)])
        self.encode_hierarchy()
        self.refresh_hierarchy()
        for i, s in enumerate(splits):
            if stop_check is not None and stop_check():
                break
            if call_back is not None:
                call_back(i)
                call_back(process_string.format(i, len(splits), s))
            q = self.query_graph(word_type)
            q = q.filter(word_type.discourse.name == s)
            q = q.order_by(word_type.begin)
            q = q.columns(word_type.id.column_name('id'), phone_type.id.column_name('phone_id'),
                        phone_type.label.column_name('phones'),
                        phone_type.begin.column_name('begins'),
                        phone_type.end.column_name('ends'))
            results = q.all()
            boundaries = []
            non_syls = []
            prev_id = None
            for w in results:
                phones = w.phones
                phone_ids = w.phone_id
                phone_begins = w.begins
                phone_ends = w.ends
                vow_inds = [i for i,x in enumerate(phones) if x in syllabics]
                if len(vow_inds) == 0:
                    cur_id = uuid1()
                    if algorithm == 'probabilistic':
                        split = split_nonsyllabic_prob(phones, onsets, codas)
                    elif algorithm == 'maxonset':
                        split = split_nonsyllabic_maxonset(phones, onsets)
                    label = '.'.join(phones)
                    row = {'id': cur_id, 'prev_id': prev_id,
                        'onset_id': phone_ids[0],
                            'break': split,
                            'coda_id':phone_ids[-1],
                            'begin': phone_begins[0],
                            'label': label,
                            'type_id': make_type_id([label], self.corpus_name),
                            'end': phone_ends[-1]}
                    non_syls.append(row)
                    prev_id = cur_id
                    continue
                for j, i in enumerate(vow_inds):
                    cur_id = uuid1()
                    cur_vow_id = phone_ids[i]
                    begin = phone_begins[i]
                    end = phone_ends[i]
                    if j == 0:
                        begin_ind = 0
                        if i != 0:
                            cur_ons_id = phone_ids[begin_ind]
                            begin = phone_begins[begin_ind]
                        else:
                            cur_ons_id = None
                    else:
                        prev_vowel_ind = vow_inds[j - 1]
                        cons_string = phones[prev_vowel_ind + 1:i]
                        if algorithm == 'probabilistic':
                            split = split_ons_coda_prob(cons_string, onsets, codas)
                        elif algorithm == 'maxonset':
                            split = split_nonsyllabic_maxonset(cons_string, onsets)
                        if split is None:
                            cur_ons_id = None
                        else:
                            begin_ind = prev_vowel_ind + 1 + split
                            cur_ons_id = phone_ids[begin_ind]
                            begin = phone_begins[begin_ind]

                    if j == len(vow_inds) - 1:
                        end_ind = len(phones) - 1
                        if i != len(phones) - 1:
                            cur_coda_id = phone_ids[end_ind]
                            end = phone_ends[end_ind]
                        else:
                            cur_coda_id = None
                    else:
                        foll_vowel_ind = vow_inds[j + 1]
                        cons_string = phones[i + 1:foll_vowel_ind]
                        if algorithm == 'probabilistic':
                            split = split_ons_coda_prob(cons_string, onsets, codas)
                        elif algorithm == 'maxonset':
                            split = split_nonsyllabic_maxonset(cons_string, onsets)
                        if split is None:
                            cur_coda_id = None
                        else:
                            end_ind = i + split
                            cur_coda_id = phone_ids[end_ind]
                            end = phone_ends[end_ind]
                    label = '.'.join(phones[begin_ind:end_ind + 1])
                    row = {'id': cur_id, 'prev_id': prev_id,
                        'vowel_id': cur_vow_id, 'onset_id': cur_ons_id,
                        'label': label,
                        'type_id': make_type_id([label], self.corpus_name),
                            'coda_id':cur_coda_id, 'begin': begin, 'end': end}
                    boundaries.append(row)
                    prev_id = cur_id
            syllables_data_to_csvs(self, boundaries, s)
            import_syllable_csv(self, s)
            nonsyls_data_to_csvs(self, non_syls, s)
            import_nonsyl_csv(self, s)

            statement = '''Match (n:syllable:{corpus})-[:spoken_in]->(d:Discourse {{name: {{discourse_name}}}}),
            (p:syllable:{corpus} {{id: n.prev_id}})-[:spoken_in]->(d)
            CREATE (p)-[:precedes]->(n)
            REMOVE n.prev_id'''
            self.execute_cypher(statement.format(corpus=self.corpus_name), discourse_name = s)
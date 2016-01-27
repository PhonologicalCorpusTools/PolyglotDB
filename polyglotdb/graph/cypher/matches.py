
from ..attributes import PauseAnnotation, AnnotationAttribute


anchor_template = '''({token_alias})-[:is_a]->({type_alias})'''
prec_template = '''({prev_type_alias})<-[:is_a]-({prev_alias})-[:precedes]->({node_alias})'''
foll_template = '''({node_alias})-[:precedes]->({foll_alias})-[:is_a]->({foll_type_alias})'''

prec_pause_template = '''{path_alias} = (:speech:word)-[:precedes_pause*0..]->({node_alias})'''
foll_pause_template = '''{path_alias} = ({node_alias})-[:precedes_pause*0..]->(:speech:word)'''


def generate_match(annotation_type, annotation_list, filter_annotations):
    annotation_list = sorted(annotation_list, key = lambda x: x.pos)
    prec_condition = ''
    foll_condition = ''
    defined = set()

    statements = []
    wheres = []
    optional_wheres = []
    current = annotation_list[0].pos
    optional_statements = []
    if isinstance(annotation_type, PauseAnnotation):
        prec = prec_pause_template
        foll = foll_pause_template
    else:
        prec = prec_template
        foll = foll_template
        anchor_string = annotation_type.for_match()
        statements.append(anchor_string)
        defined.update(annotation_type.withs)
    for a in annotation_list:
        where = ''
        if a.pos == 0:
            if isinstance(annotation_type, PauseAnnotation):
                anchor_string = annotation_type.for_match()

                statements.append(anchor_string)
                defined.update(annotation_type.withs)
            continue
        elif a.pos < 0:

            kwargs = {}
            if isinstance(annotation_type, PauseAnnotation):
                kwargs['node_alias'] = AnnotationAttribute('word',0,a.corpus).alias
                kwargs['path_alias'] = a.path_alias
                where = a.additional_where()
            else:
                kwargs['node_alias'] = AnnotationAttribute(a.type,0,a.corpus).alias
                kwargs['prev_alias'] = a.define_alias
                kwargs['prev_type_alias'] = a.define_type_alias
            anchor_string = prec.format(**kwargs)
        elif a.pos > 0:

            kwargs = {}
            if isinstance(annotation_type, PauseAnnotation):
                kwargs['node_alias'] = AnnotationAttribute('word',0,a.corpus).alias
                kwargs['path_alias'] = a.path_alias
                where = a.additional_where()
            else:
                kwargs['node_alias'] = AnnotationAttribute(a.type,0,a.corpus).alias
                kwargs['foll_alias'] = a.define_alias
                kwargs['foll_type_alias'] = a.define_type_alias
            anchor_string = foll.format(**kwargs)
        if a in filter_annotations:
            statements.append(anchor_string)
            if where:
                wheres.append(where)
        else:
            optional_statements.append(anchor_string)
            if where:
                optional_wheres.append(where)
        defined.add(a.alias)
        if isinstance(annotation_type, PauseAnnotation):
            defined.add(a.path_alias)
        else:
            defined.add(a.type_alias)
    return statements, optional_statements, defined, wheres, optional_wheres

hierarchy_template = '''({contained_alias})-[:contained_by*1..]->({containing_alias})'''

def generate_hierarchical_match(annotation_levels, hierarchy):
    statements = []
    annotation_types = [x.type for x in annotation_levels.keys()]
    for k in sorted(annotation_types):
        if k in hierarchy:
            supertype = hierarchy[k]
            while supertype not in annotation_types:
                if supertype is None:
                    break
                supertype = hierarchy[supertype]
            if supertype is None:
                continue
            sub = AnnotationAttribute(k, 0)
            sup = AnnotationAttribute(supertype, 0)
            statement = hierarchy_template.format(contained_alias = sub.alias,
                                                    containing_alias = sup.alias)
            if statement not in statements:
                statements.append(statement)
    return statements
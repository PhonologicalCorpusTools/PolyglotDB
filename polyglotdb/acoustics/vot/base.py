import tempfile

from conch import analyze_segments
from conch.analysis.segments import SegmentMapping, FileSegment
from conch.analysis.autovot import AutoVOTAnalysisFunction

from ..segments import generate_utterance_segments, generate_segments
from ...query.annotations.models import LinguisticAnnotation
from ...exceptions import SpeakerAttributeError
from ..classes import Track, TimePoint
from ..utils import PADDING


def analyze_vot(corpus_context,
                  stop_label='stops',
                  classifier="/autovot/experiments/models/bb_jasa.classifier",
                  vot_min=5,
                  vot_max=100,
                  window_min=-30,
                  window_max=30,
                  call_back=None,
                  stop_check=None, multiprocessing=False):
    """

    Parameters
    ----------
    corpus_context : :class:`~polyglotdb.CorpusContext`
    source
    call_back
    stop_check

    Returns
    -------

    """
    if not corpus_context.hierarchy.has_type_subset('phone', stop_label):
        raise Exception('Phones do not have a "{}" subset.'.format(stop_label))
    stop_mapping = generate_segments(corpus_context, annotation_type='phone', subset='stops', padding=PADDING, file_type="consonant").grouped_mapping('discourse')
    segment_mapping = SegmentMapping()
    vot_func = AutoVOTAnalysisFunction(autovot_binaries_path = corpus_context.config.autovot_path ,\
            classifier_to_use=classifier,
            min_vot_length=vot_min,
            max_vot_length=vot_max,
            window_min=window_min,
            window_max=window_max
            )
    for discourse in corpus_context.discourses:
        if (discourse,) in stop_mapping:
            sf = corpus_context.discourse_sound_file(discourse)
            speaker_mapped_stops = {}
            discourse_speakers = set()
            for x in stop_mapping[(discourse,)]:
                if x["speaker"] in speaker_mapped_stops:
                    speaker_mapped_stops[x["speaker"]].append((x["begin"], x["end"], x["id"]))
                else:
                    speaker_mapped_stops[x["speaker"]] = [(x["begin"], x["end"], x["id"])]
                    discourse_speakers.add(x["speaker"])
            for speaker in discourse_speakers:
                seg = FileSegment(sf["consonant_file_path"], sf["speech_begin"], sf["speech_end"], name=discourse)
                seg.properties["vot_marks"] = speaker_mapped_stops[speaker]
                segment_mapping.segments.append(seg)

    output = analyze_segments(segment_mapping, vot_func, stop_check=stop_check, multiprocessing=multiprocessing)
    #NOTE: possible that autovot conch integration doesn't check if nothing is returned for a given segment, 
    # do something to make sure len(output)==len(segment_mapping) in conch
    #TODO: fix this
    if not corpus_context.hierarchy.has_subannotation_type("vot"):
        corpus_context.hierarchy.add_subannotation_type(corpus_context, "phone", "vot", properties=[("begin", float), ("end",float)])
        corpus_context.encode_hierarchy()

    for discourse, discourse_output in output.items():
        for (begin, end, stop_id) in discourse_output:
            model = LinguisticAnnotation(corpus_context)
            model.load(stop_id)
            model.add_subannotation("vot", begin=begin, end=begin+end)
            model.save()
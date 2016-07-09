

from .audio import AudioContext
from .importable import ImportContext
from .lexical import LexicalContext
from .pause import PauseContext
from .utterance import UtteranceCorpus
from .structured import StructuredContext
from .syllabic import SyllabicContext
from .spoken import SpokenContext
from .summarized import SummarizedContext


class CorpusContext(StructuredContext, ImportContext, LexicalContext,
                    PauseContext, UtteranceCorpus, AudioContext,
                    SyllabicContext, SpokenContext, SummarizedContext):
    pass




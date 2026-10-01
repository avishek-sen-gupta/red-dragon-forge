"""CorpusFile -- a corpus config file, as far as the corpus stages read it."""

from cobble.corpus_table import CorpusTable
from pydantic import BaseModel, ConfigDict


class CorpusFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    corpus: CorpusTable

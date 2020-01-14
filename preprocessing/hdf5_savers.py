from abc import ABC, abstractmethod

import h5py
import numpy as np
from tqdm import tqdm

from qa_utils.io import dump_pkl_file
from qa_utils.preprocessing.dataset import Dataset, Trainset, Testset
from qa_utils.text import build_vocab, compute_idfs


class Hdf5Saver(ABC):
    """Saves a dataset to hdf5 format.
    """

    def __init__(self, dataset: Dataset, tokenizer, max_vocab_size, vocab_outfile, train_outfile=None, dev_outfile=None,
                 test_outfile=None):
        """Construct a h5py saver object. Each dataset that has no output path specified will be ignored, meaning at
        least one output path must be provided.

        Args:
            dataset: Dataset to save to hdf5.
            train_outfile: path to the hdf5 output file for the train set.
            dev_outfile: path to the hdf5 output file for the dev set.
            test_outfile: path to the hdf5 output file for the test set.
        """
        self.dataset = dataset
        self.tokenizer = tokenizer
        self.max_vocab_size = max_vocab_size
        self.vocab_outfile = vocab_outfile

        self.train_outpath = train_outfile
        self.dev_outpath = dev_outfile
        self.test_outpath = test_outfile

        out_paths = [train_outfile, dev_outfile, test_outfile]
        assert any(out_paths), 'you need to specify at least one output filepath.'
        self.train_out, self.dev_out, self.test_out = (h5py.File(fpath, 'w') if fpath else None for fpath in
                                                       out_paths)

        # tokenize dataset
        self._build_vocab()

    def build_all(self):
        """Exports each split of dataset to hdf5 if an output file was specified for it.
        """
        if self.train_out:
            self._save_train_set()
        if self.test_out:
            self._save_candidate_set('test')
        if self.dev_out:
            self._save_candidate_set('dev')

    def _save_candidate_set(self, split):
        """Saves a candidate type set i.e. Dataset.testset or Dataset.devset to hdf5.

        Args:
            split (str): either 'dev' or 'test'.

        """
        fp, dataset = (self.dev_out, self.dataset.devset) if split == 'dev' else (self.test_out, self.dataset.testset)

        print('saving to', fp.filename, '...')
        self._define_candidate_set(fp, self._n_out_samples(dataset))
        idx = 0

        for q_id, query, doc, label in tqdm(dataset):
            self._save_candidate_row(fp, q_id, query, doc, label, idx)
            idx += 1

    def _save_train_set(self):
        """Saves the trainset to hdf5.
        """
        print("saving", self.train_outpath, "...")
        self._define_trainset(self.train_out, self._n_out_samples(self.dataset.trainset))
        idx = 0

        for query, pos_doc, neg_docs in tqdm(self.dataset.trainset):
            self._save_train_row(self.train_out, query, pos_doc, neg_docs, idx)
            idx += 1

    def _build_vocab(self):
        """Build and export a vocabulary given the dataset."""
        collection = list(self.dataset.queries.values()) + list(self.dataset.docs.values())
        self.word_to_index = build_vocab(collection, self.tokenizer, max_vocab_size=self.max_vocab_size)
        self.index_to_word = {v: k for k, v in self.word_to_index.items()}
        dump_pkl_file(self.index_to_word, self.vocab_outfile)

    def _words_to_index(self, words, unknown_token='<UNK>'):
        """Turns a list of words into integer indices using self.word_to_index.

        Args:
            words (list(str)): list of words.

        Returns:
            list(int): a list if integers encoding words.
        """
        tokens = []
        for token in words:
            try:
                tokens.append(self.word_to_index[token])
            # out of vocabulary
            except KeyError:
                tokens.append(self.word_to_index[unknown_token])
        return tokens

    @abstractmethod
    def _define_trainset(self, dataset_fp, n_out_examples):
        """Specify the structure of the hdf5 output file.

        Args:
            dataset_fp: file pointer to the hdf5 output file.
            n_out_examples: number of examples that will be generated for this dataset.
        """

    @abstractmethod
    def _define_candidate_set(self, dataset_fp, n_out_examples):
        """Specify the structure of the hdf5 output file for candidate type sets.

        Args:
            dataset_fp: file pointer to the hdf5 output file.
            n_out_examples: number of examples that will be generated for this dataset.
        """

    @abstractmethod
    def _n_out_samples(self, dataset):
        """Computes the number of output examples generated for either train, test or dev set.

        Args:
            dataset: either Trainset or Testset from qa_utils.

        Returns:
            int: number of total output samples.

        """

    @abstractmethod
    def _save_train_row(self, fp, query, pos_doc, neg_docs, idx):
        """The function that saves an item from the Dataset.trainset after applying _transform_train_row. It's saved to
        a hdf5 file as defined in _define_trainset().

        Args:
            fp: filepointer to the h5py file.
            query (list(int)): the tokenized query.
            pos_doc (list(int)): the tokenized positive document.
            neg_docs (list(list(int))): list of tokenized negative documents.
            idx: current sample index.
        """

    @abstractmethod
    def _save_candidate_row(self, fp, q_id, query, doc, label, idx):
        """The function that saves an item from the Dataset.devset or Dataset.trainset after applying
        _transform_candidate_row. It's saved a hdf5 file as defined in _define_candidate_set().

        Args:
            fp: filepointer to the h5py file.
            q_id: integer identifier for the query.
            query (list(int)): the tokenized query.
            doc (list(int)): the tokenized document.
            label: label for the query document pair.
            idx: current sample index.
        """


class DuetHhdf5Saver(Hdf5Saver):
    """Class for transforming and saving a qa_utils dataset into an hdf5 file that matches the input specification of
    DUET V2.
    """

    def __init__(self, dataset: Dataset, tokenizer, max_vocab_size, vocab_outfile, idf_outfile, max_query_len,
                 max_doc_len, train_outfile=None, dev_outfile=None, test_outfile=None):
        """Construct a hdf5 saver for qa_util Datasets.

        Args:
            dataset: the dataset to save as hdf5.
            max_query_len: truncate queries to this length in words.
            max_doc_len: truncate documents to this length in words.
            vocab_outfile: a pickle file where a word to index dictionary will be exported to.
            max_vocab_size: the maximum number of words in the vocabulary, only keeping the most frequent ones. Uses all
            if None.
        """

        super().__init__(dataset, tokenizer, max_vocab_size, vocab_outfile, train_outfile, dev_outfile, test_outfile)

        # compute idfs for weighting of the interaction matrix
        vocab_tokens = set(self.word_to_index.keys())
        self.idfs = compute_idfs(vocab_tokens, dataset.docs.values(), self.tokenizer)
        # map token ids to idfs
        self.idfs = dict(map(lambda x: (self.word_to_index[x[0]], x[1]), self.idfs.items()))
        dump_pkl_file(self.idfs, idf_outfile)

        print('tokenizing...')
        self.dataset.transform_docs(lambda x: self._words_to_index(self.tokenizer.tokenize(x))[:max_doc_len])
        self.dataset.transform_queries(lambda x: self._words_to_index(self.tokenizer.tokenize(x)[:max_query_len]))

    def _define_trainset(self, dataset_fp, n_out_examples):
        vlen_int64 = h5py.special_dtype(vlen=np.dtype('int64'))
        dataset_fp.create_dataset('queries', shape=(n_out_examples,), dtype=vlen_int64)
        dataset_fp.create_dataset('pos_docs', shape=(n_out_examples,), dtype=vlen_int64)
        dataset_fp.create_dataset('neg_docs', shape=(n_out_examples,), dtype=vlen_int64)

    def _define_candidate_set(self, dataset_fp, n_out_examples):
        vlen_int64 = h5py.special_dtype(vlen=np.dtype('int64'))
        dataset_fp.create_dataset('queries', shape=(n_out_examples,), dtype=vlen_int64)
        dataset_fp.create_dataset('docs', shape=(n_out_examples,), dtype=vlen_int64)

        dataset_fp.create_dataset('q_ids', shape=(n_out_examples,), dtype=np.dtype('int64'))
        dataset_fp.create_dataset('labels', shape=(n_out_examples,), dtype=np.dtype('int64'))

    def _n_out_samples(self, dataset):
        if isinstance(dataset, Trainset):
            # duet trains on triplets i.e. pairs of (q, pos, neg)
            return len(dataset.pos_pairs) * dataset.num_neg_examples
        elif isinstance(dataset, Testset):
            return len(dataset)
        else:
            raise TypeError('Dataset needs to be of type Trainset or Testset.')

    def _save_train_row(self, fp, query, pos_doc, neg_docs, idx):
        for neg_ids in neg_docs:
            fp['queries'][idx] = query
            fp['pos_docs'][idx] = pos_doc
            fp['neg_docs'][idx] = neg_ids

    def _save_candidate_row(self, fp, q_id, query, doc, label, idx):
        fp['q_ids'][idx] = q_id
        fp['queries'][idx] = query
        fp['docs'][idx] = doc
        fp['labels'][idx] = label

    def _words_to_index(self, words, unknown_token='<UNK>'):
        """Turns a list of words into integer indices using self.word_to_index.

        Args:
            words (list(str)): list of words.

        Returns:
            list(int): a list if integers encoding words.
        """
        tokens = []
        for token in words:
            try:
                tokens.append(self.word_to_index[token])
            # out of vocabulary
            except KeyError:
                tokens.append(self.word_to_index[unknown_token])
        return tokens

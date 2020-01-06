import math
from collections import Counter
from functools import partial
from multiprocessing.pool import Pool

import numpy as np
from tqdm import tqdm


def build_vocab(collection, tokenizer, special_tokens=('<UNK>', '<PAD>', '<EOS>', '<START>'),
                max_vocab_size=None):
    """Build a vocabulary from a collection of strings.

    Args:
        collection: iterable of strings to generate vocabulary from.
        tokenizer: tokenizer that needs to provide a tokenize() method.
        special_tokens: list of special tokens to add to the vocabulary. They will be assigned to ids in the range from
        0 - len(special_tokens)-1.
        max_vocab_size: maximum number of words in the vocabulary, only keeping the most frequent words. Uses all words
        if None.

    Returns:
        dict: A mapping from each word in the vocabulary to its integer id.
    """
    if max_vocab_size is not None:
        assert len(
            special_tokens) <= max_vocab_size, 'the vocabulary needs to be large enough to hold the special tokens.'

    freqs = Counter()
    print('building vocabulary...')
    with Pool(processes=None) as p:
        for tokens in tqdm(p.imap(tokenizer.tokenize, collection, chunksize=1024), total=len(collection)):
            freqs.update(tokens)

    for token in special_tokens:
        freqs[token] = math.inf  # guarantees specials tokens to be included
    freqs = dict(freqs.most_common(max_vocab_size))
    vocab = {word: i for i, word in enumerate(freqs.keys())}

    return vocab


def doc_to_bow(document, tokenizer):
    """Tokenize a document using tokenizer and return it as set.

    Args:
        document: the document to turn into a BOW.
        tokenizer: tokenizes the document.

    Returns:
        set: a set of words from the vocabulary that occur in the document.

    """
    return set(tokenizer.tokenize(document))


def compute_idfs(vocab, documents, tokenizer):
    """Compute the IDF (Robertson-Walker definition) for each term in a vocab given a corpus of tokenized bag of words
    documents.

    Args:
        vocab (Iterable): a set of words/tokens of a vocabulary.
        documents (Iterable): a list of tokenized documents.

    Returns:
        dict(str, float): a mapping from each word in the vocabulary to its idf.

    """
    dfs = {word: 0 for word in vocab}
    print('computing dfs...')

    func = partial(doc_to_bow, tokenizer=tokenizer)
    # default to cpu count
    n_docs = len(documents)
    with Pool(processes=None) as p:
        for bow_doc in tqdm(p.imap(func, documents, chunksize=1024), total=n_docs):
            for word in bow_doc:
                dfs[word] += 1

    def _idf(term_freq):
        return np.log(n_docs / (term_freq + 1)) / np.log(n_docs)

    print('computing idfs from dfs...')
    idfs = dict(map(lambda x: (x[0], _idf(x[1])), dfs.items()))
    print('done')

    return idfs


def indices_to_words(indices, index_to_word):
    return list(map(lambda x: index_to_word[x], indices))

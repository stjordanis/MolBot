from keras import optimizers
from keras import Sequential
from keras.layers import LSTM
from keras.layers import Dense
from keras.layers import Activation
from keras.layers import TimeDistributed
from keras.callbacks import TensorBoard
from keras.layers import Lambda
from keras.models import load_model
import keras.backend as K
import copy
from random import  shuffle
import numpy as np
import re
import pickle
from sklearn.base import BaseEstimator
import utils
import sklearn.model_selection as modsel
import random

class _Model(BaseEstimator):
    """
    This is the parent class to the to different models.
    """

    def __init__(self, tensorboard, hidden_neurons_1, hidden_neurons_2, dropout_1, dropout_2,
                 batch_size, epochs, smiles, learning_rate):
        """
        This function initialises the parent class common to both Model 1 and 2.

        :param tensorboard: whether to log progress to tensorboard or not
        :type tensorboard: bool
        :param hidden_neurons_1: number of hidden units in the first LSTM
        :type hidden_neurons_1: int
        :param hidden_neurons_2: number of hidden units in the second LSTM
        :type hidden_neurons_2: int
        :param dropout_1: dropout rate in the first LSTM
        :type dropout_1: float
        :param dropout_2:  dropout rate in the 2nd LSTM
        :type dropout_2: float
        :param batch_size: Size of the data set batches to use during training
        :type batch_size: int
        :param epochs: number of iterations of training
        :type epochs: int
        :param smiles: list of smiles strings from which to learn
        :type smiles: list of strings
        :param learning_rate: size of the step taken by the optimiser
        :type learning_rate: float > 0
        """

        self.tensorboard = self._set_tensorboard(tensorboard)
        self.hidden_neurons_1 = self._set_hidden_neurons(hidden_neurons_1)
        self.hidden_neurons_2 = self._set_hidden_neurons(hidden_neurons_2)
        self.dropout_1 = self._set_dropout(dropout_1)
        self.dropout_2 = self._set_dropout(dropout_2)
        self.batch_size = self._set_provisional_batch_size(batch_size)
        self.epochs = self._set_epochs(epochs)
        self.learning_rate = self._set_learning_rate(learning_rate)

        self.model = None
        self.loaded_model = None
        self.idx_to_char = None
        self.char_to_idx = None
        self.max_size = None
        self.n_feat = None
        self.padded_smiles = None
        if not isinstance(smiles, type(None)):
            self.smiles = self._check_smiles(smiles)
        else:
            self.smiles = None

    def _set_tensorboard(self, tb):

        if utils.is_bool(tb):
            return tb
        else:
            raise utils.InputError("Parameter Tensorboard should be either true or false. Got %s" % (str(tb)))

    def _set_hidden_neurons(self, h):
        if utils.is_positive_integer(h):
            return h
        else:
            raise utils.InputError("The number of hidden neurons should be a positive non zero integer. Got %s." % (str(h)))

    def _set_dropout(self, drop):
        if drop >= 0.0 and drop < 1.0:
            return drop
        else:
            raise utils.InputError(
                "The dropout rate should be between 0 and 1. Got %s." % (str(drop)))

    def _set_provisional_batch_size(self, batch_size):
        if batch_size != "auto":
            if not utils.is_positive_integer(batch_size):
                raise utils.InputError("Expected 'batch_size' to be a positive integer. Got %s" % str(batch_size))
            elif batch_size == 1:
                raise utils.InputError("batch_size must be larger than 1.")
            return int(batch_size)
        else:
            return batch_size

    def _set_batch_size(self):

        if self.batch_size == 'auto':
            batch_size = min(100, self.n_samples)
        else:
            if self.batch_size > self.n_samples:
                print("Warning: batch_size larger than sample size. It is going to be clipped")
                return self.n_samples
            else:
                batch_size = self.batch_size

        better_batch_size = utils.ceil(self.n_samples, utils.ceil(self.n_samples, batch_size))

        return better_batch_size

    def _set_epochs(self, epochs):
        if utils.is_positive_integer(epochs):
            return epochs
        else:
            raise utils.InputError("The number of epochs should be a positive integer. Got %s." % (str(epochs)))

    def _set_learning_rate(self, lr):
        """
        This function checks that the learning rate is a float larger than zero

        :param lr: learning rate
        :type: float > 0
        :return: approved learning rate
        """

        if isinstance(lr, (float, int)):
            if lr > 0.0:
                return lr
            else:
                raise utils.InputError("The learning rate should be larger than 0.")
        else:
            raise utils.InputError("The learning rate should be number larger than 0.")

    def _check_smiles(self, smiles):
        if utils.is_array_like(smiles):
            for item in smiles:
                if not isinstance(item, str):
                    raise utils.InputError("Smiles should be a list of string.")

            return smiles
        else:
            raise utils.InputError("Smiles should be a list of string.")

    def _modify_model_for_predictions(self, model, temperature):
        """
        This function modifies the model for predict time by adding a temperature factor to the softmax activation
        function.

        :param model: the model to modify
        :type model: keras model
        :param temperature: temperature that modifies the softmax
        :type temperature: float > 0 and <= 1
        :return: The modified model
        """

        model.pop()
        model.pop()
        model.add(Lambda(lambda x: x / temperature))
        model.add(Activation('softmax'))

        return model

    def fit(self, X):
        """
        This function fits the parameters of a GRNN to the data provided.

        :param X: list of smiles or list of indices of the smiles to use
        :type X: list of strings or list of ints
        :return: None
        """

        X_hot, y_hot = self._initialise_data_fit(X)

        X_hot_train, X_hot_val, y_hot_train, y_hot_val = modsel.train_test_split(X_hot, y_hot, test_size=0.05)

        self.n_samples = X_hot_train.shape[0]
        self.max_size = X_hot_train.shape[1]
        self.n_feat = X_hot_train.shape[2]

        batch_size = self._set_batch_size()

        if isinstance(self.model, type(None)) and isinstance(self.loaded_model, type(None)):
            self._generate_model()

            if self.tensorboard == True:
                tensorboard = TensorBoard(log_dir='./tb',
                                          write_graph=True, write_images=False)
                callbacks_list = [tensorboard]
                self.model.fit(X_hot_train, y_hot_train, batch_size=batch_size, verbose=1, epochs=self.epochs,
                               callbacks=callbacks_list, validation_data=(X_hot_val, y_hot_val))
            else:
                self.model.fit(X_hot_train, y_hot_train, batch_size=batch_size, verbose=1, epochs=self.epochs,
                               validation_data=(X_hot_val, y_hot_val))

        elif not isinstance(self.model, type(None)):
            if self.tensorboard == True:
                tensorboard = TensorBoard(log_dir='./tb',
                                          write_graph=True, write_images=False)
                callbacks_list = [tensorboard]
                self.model.fit(X_hot_train, y_hot_train, batch_size=batch_size, verbose=1, epochs=self.epochs,
                               callbacks=callbacks_list, validation_data=(X_hot_val, y_hot_val))
            else:
                self.model.fit(X_hot_train, y_hot_train, batch_size=batch_size, verbose=1, epochs=self.epochs,
                               validation_data=(X_hot_val, y_hot_val))

        elif not isinstance(self.loaded_model, type(None)):
            if self.tensorboard == True:
                tensorboard = TensorBoard(log_dir='./tb',
                                          write_graph=True, write_images=False)
                callbacks_list = [tensorboard]
                self.loaded_model.fit(X_hot_train, y_hot_train, batch_size=batch_size, verbose=1, epochs=self.epochs,
                                      callbacks=callbacks_list, validation_data=(X_hot_val, y_hot_val))
            else:
                self.loaded_model.fit(X_hot_train, y_hot_train, batch_size=batch_size, verbose=1,
                                      epochs=self.epochs, validation_data=(X_hot_val, y_hot_val))

        else:
            raise utils.InputError("No model has been fit already or has been loaded.")

    def fit_with_rl(self, n_train_episodes=10, temperature=1.0, max_length=100):
        """
        This function fits the model using reinforcement learning.

        :param n_train_episodes: number of episodes on which to learn
        :type n_train_episodes: positive int
        :param temperature: Temperature factor in the softmax
        :type temperature: positive float
        :param max_length: maximum length of an episode
        :type max_length: int
        :return: None
        """

        if utils.is_none(self.model) and utils.is_none(self.loaded_model):
            raise utils.InputError("Fit with reinforcement learning can only be called after the model has been trained.")

        self._fit_with_rl(n_train_episodes, temperature, max_length)

    def _generate_rl_training_fn(self, model_agent):
        """
        This function extends the model so that Reinforcement Learning can be done.

        :param temperature: the temperature of the softmax parameter
        :type temperature: positive float
        :return: the model and the training function
        :rtype: a keras object and a keras function
        """

        # The first argument is the model input
        hot_encoded_sequence = model_agent.input

        # The probabilities that the agent would assign in each state
        agent_action_prob_placeholder = model_agent.output

        # The log likelihood of a sequence from a prior
        prior_loglikelihood = K.placeholder(shape=(None,), name="prior_loglikelihood")

        # The log likelihood of a sequence from the agent
        individual_action_probability = K.sum(hot_encoded_sequence[:, 1:] * agent_action_prob_placeholder[:, :-1], axis=-1)
        agent_likelihood = K.prod(individual_action_probability)
        agent_loglikelihood = K.log(agent_likelihood)

        # Reward that the sequence has obtained
        reward_placeholder = K.placeholder(shape=(None,), name="reward")

        # Augmented log-likelihood: prior log lokelihood + sigma * desirability of the sequence
        sigma = K.constant(60)
        desirability = reward_placeholder
        augmented_likelihood = prior_loglikelihood + sigma * desirability

        # Loss function
        loss = K.pow(augmented_likelihood - agent_loglikelihood, 2)

        # Optimiser and updates
        optimiser = optimizers.Adam(lr=0.0005, clipnorm=3.0)
        updates = optimiser.get_updates(params=model_agent.trainable_weights, loss=loss)

        rl_training_function = K.function(inputs=[hot_encoded_sequence, prior_loglikelihood, reward_placeholder],
                                          outputs=[], updates=updates)

        return rl_training_function

    def _calculate_reward(self, X_string):
        """
        This function calculates the reward for a particular molecule.

        :param X_string: A SMILES molecule
        :type X_string: string
        :return: the reward
        :rtype: float
        """

        from rdkit.Chem import Descriptors, MolFromSmiles
        from rdkit import rdBase
        rdBase.DisableLog('rdApp.error')

        m = MolFromSmiles(X_string)

        if utils.is_none(m):
            return None

        TPSA = Descriptors.TPSA(m)

        return TPSA

    def predict(self, X=None, frag_length=5, temperature=1.0, max_length=100):
        """
        This function predicts some smiles from either nothing or from fragments of smiles strings.

        :param X: list of smiles strings or nothing
        :type X: list of str
        :param frag_length: length of smiles string fragment to use.
        :type frag_length: int
        :param temperature: factor that modifies the softmax function at predict time.
        :type temperature: float > 0 and <= 1
        :param max_length: Maximum length of the strings to be predicted.
        :type max_length: int larger than 0
        :return: list of smiles string
        :rtype: list of str
        """
        if temperature <= 0:
            raise utils.InputError("Temperature parameter should be > 0.0. Got %s" % (str(temperature)))
        if not isinstance(max_length, type(int)) and max_length <= 0:
            raise utils.InputError("The length of the predicted strings should be an integer larger than 0.")

        X_strings, X_hot = self._initialise_data_predict(X, frag_length)

        if isinstance(self.model, type(None)) and isinstance(self.loaded_model, type(None)):
            raise Exception("The model has not been fit and no saved model has been loaded.\n")

        elif isinstance(self.model, type(None)):
            predictions = self._predict(X_strings, X_hot, self.loaded_model, temperature, max_length)

        else:
            predictions = self._predict(X_strings, X_hot, self.model, temperature, max_length)

        return predictions

    def score(self, X=None):
        """
        This function takes in smiles strings and scores the model on the predictions. The score is the percentage of
         valid smiles strings that have been predicted.

        :param X: smiles strings
        :type X: list of strings
        :return: score
        :rtype: float
        """

        try:
            from rdkit import Chem
        except ModuleNotFoundError:
            raise ModuleNotFoundError("RDKit is required for scoring.")

        predictions = self.predict(X)

        n_valid_smiles = 0

        for smile_string in predictions:
            try:
                mol = Chem.MolFromSmiles(smile_string)
                if not isinstance(mol, type(None)):
                    n_valid_smiles += 1
            except Exception:
                pass

        score = n_valid_smiles/len(predictions)

        return score

    def score_similarity(self, X_1, X_2):
        """
        This function calculates the average Tanimoto similarity between each molecule in X_1 and those in X_2. It
        returns all the average Tanimoto coefficients and the percentage of duplicates.

        :param X_1: list of smiles strings to compare
        :param X_2: list of smiles strings acting as reference
        :return: Tanimoto coefficients and the percentage of duplicates
        :rtype: list of floats, float
        """

        try:
            from rdkit import Chem
            from rdkit.Chem.Fingerprints import FingerprintMols
            from rdkit import DataStructs
        except ModuleNotFoundError:
            raise ModuleNotFoundError("RDKit is required for scoring the similarity.")

        # Making the smiles strings in rdkit molecules
        mol_1, invalid_1 = self._make_rdkit_mol(self._check_smiles(X_1))
        mol_2, invalid_2 = self._make_rdkit_mol(self._check_smiles(X_2))

        # Turning the molecules in Daylight fingerprints
        fps_1 = [FingerprintMols.FingerprintMol(x) for x in mol_1]
        fps_2 = [FingerprintMols.FingerprintMol(x) for x in mol_2]

        # Obtaining similarity measure
        tanimoto_coeff = []
        n_duplicates = 0

        for i in range(len(fps_1)):
            sum_tanimoto = 0
            for j in range(len(fps_2)):
                coeff = DataStructs.FingerprintSimilarity(fps_1[i], fps_2[j])
                sum_tanimoto += coeff
                if coeff == 1:
                    n_duplicates += 1

            avg_tanimoto = sum_tanimoto/len(fps_2)
            tanimoto_coeff.append(avg_tanimoto)

        if len(fps_1) != 0:
            percent_duplicates = n_duplicates/len(fps_1)
        else:
            percent_duplicates = 1

        return tanimoto_coeff, percent_duplicates

    def save(self, filename='model'):
        """
        This function enables to save the trained model so that then training or predictions can be done at a later stage.

        :param filename: Name of the file in which to save the model.
        :return: None
        """
        model_name = filename + ".h5"
        dict_name = filename + ".pickle"

        if not isinstance(self.model, type(None)):
            self.model.save(model_name, overwrite=False)
        elif not isinstance(self.loaded_model, type(None)):
            self.loaded_model.save(model_name, overwrite=False)
        else:
            raise utils.InputError("No model to be saved.")

        pickle.dump([self.char_to_idx, self.idx_to_char, self.max_size], open( dict_name, "wb" ))

    def load(self, filename='model'):
        """
        This function loads a model that has been previously saved.

        :param filename: Name of the file in which the model has been previously saved.
        :return: None
        """
        model_name = filename + ".h5"
        dict_name = filename + ".pickle"

        self.loaded_model = load_model(model_name)
        self.loaded_prior = load_model(model_name)

        idx_dixt = pickle.load(open(dict_name, "rb"))
        self.char_to_idx = idx_dixt[0]
        self.idx_to_char = idx_dixt[1]
        self.max_size = idx_dixt[2]

        self.n_feat = len(self.char_to_idx)

    def _make_rdkit_mol(self, X):
        """
        This function takes a list of smiles strings and returns a list of rdkit objects for the valid smiles strings.

        :param X: list of smiles
        :return: list of rdkit objects
        """

        X = self._check_smiles(X)

        mol = []
        invalid = 0

        for smile in X:
            try:
                molecule = Chem.MolFromSmiles(smile)
                if not isinstance(molecule, type(None)):
                    mol.append(molecule)
                else:
                    invalid += 1
            except Exception:
                pass

        return mol, invalid

class Model_1(_Model):
    """
    Estimator Model 1

    This estimator learns from segments of smiles strings all of the same length and the next character along the sequence.
    When presented with a new smiles fragment it predicts the most likely next character."""

    def __init__(self, tensorboard=False, hidden_neurons_1=256, hidden_neurons_2=256, dropout_1=0.3, dropout_2=0.5,
                 batch_size="auto", epochs=4, window_length=10, smiles=None, learning_rate=0.001):
        """
        This function uses the initialiser of the parent class and initialises the window length.

        :param tensorboard: whether to log progress to tensorboard or not
        :type tensorboard: bool
        :param hidden_neurons_1: number of hidden units in the first LSTM
        :type hidden_neurons_1: int
        :param hidden_neurons_2: number of hidden units in the second LSTM
        :type hidden_neurons_2: int
        :param dropout_1: dropout rate in the first LSTM
        :type dropout_1: float
        :param dropout_2:  dropout rate in the 2nd LSTM
        :type dropout_2: float
        :param batch_size: Size of the data set batches to use during training
        :type batch_size: int
        :param epochs: number of iterations of training
        :type epochs: int
        :param window_length: size of the smiles fragments from which to learn
        :type window_length: int
        :param smiles: list of smiles strings from which to learn
        :type smiles: list of strings
        """

        super(Model_1, self).__init__(tensorboard, hidden_neurons_1, hidden_neurons_2, dropout_1, dropout_2,
                 batch_size, epochs, smiles, learning_rate)

        # TODO make check for window length
        self.window_length = window_length

        if not isinstance(self.smiles, type(None)):
            self.X_hot, self.y_hot = self._hot_encode(smiles)

    def _initialise_data_fit(self, X):
        """
        This function checks whether the smiles strings are stored in the class. Then it checks that X is a list of
        indices specifying which data samples to use. Then, it returns the appropriate fragments of smiles strings hot
        encoded.

        :param X: either list of smiles strings or indices.
        :type X: either list of strings or list of ints
        :return: the fragments of smiles strings hot encoded and the following character
        :rtype: numpy arrays of shape (n_samples, n_window_length, n_unique characters) and (n_samples, n_unique_characters)
        """

        if not isinstance(self.smiles, type(None)):
            if not utils.is_positive_integer_or_zero_array(X):
                raise utils.InputError("The indices need to be positive or zero integers.")

            # This line is just so that the indices are ints of the right shape for Osprey
            X = np.reshape(np.asarray(X).astype(np.int32), (np.asarray(X).shape[0],))

            window_idx = self._idx_to_window_idx(X)      # Converting from the index of the sample to the index of the windows
            X_hot = np.asarray([self.X_hot[i] for i in window_idx])
            y_hot = np.asarray([self.y_hot[i] for i in window_idx])
        else:
            X_strings = self._check_smiles(X)
            X_hot, y_hot = self._hot_encode(X_strings)

        return X_hot, y_hot

    def _initialise_data_predict(self, X, frag_length):
        """
        X can either be a list of smiles strings or the indices to the samples to be used for prediction. In the latter
        case, the data needs to have been stored inside the class.

        This function takes the smiles strings and splits them into fragments (of length specified by the window length)
        to be used for predictions. The first fragment of each smile is used for prediction.

        :param X: list of smiles or list of indices
        :type X: list of strings or list of ints
        :param frag_length: parameter not needed for model 1
        :return: list of the first fragment of each smile string specified and its one-hot encoded version.
        :rtype: list of strings, numpy array of shape (n_samples, n_window_length, n_unique_char)
        """

        if isinstance(X, type(None)):
            raise utils.InputError("Model_1 can only predict from fragments of length %i. No smiles given." % (self.window_length))

        if not isinstance(self.smiles, type(None)):
            if not utils.is_positive_integer_or_zero_array(X):
                raise utils.InputError("Indices should be passed to the predict function since smiles strings are already stored in the class.")

            # This line is just so that the indices are ints of the right shape for Osprey
            X = np.reshape(np.asarray(X).astype(np.int32), (np.asarray(X).shape[0],))

            X_strings_padded = [self.padded_smiles[i] for i in X] # Using the 'G' and 'E' padded version since the hot encoded version has also the padding
            window_idx = self._idx_to_window_idx(X)
            X_hot = np.asarray([self.X_hot[i] for i in window_idx])
        else:
            self._check_smiles(X)
            X_hot, _ = self._hot_encode(X)
            # Adding G and E at the ends since the hot version has it:
            X_strings_padded = []
            for item in X:
                X_strings_padded.append("G" + item + "E")

        return X_strings_padded, X_hot

    def _generate_model(self):
        """
        This function generates the model.
        :return: None
        """
        model = Sequential()
        # This will output (max_size, n_hidden_1)
        model.add(LSTM(units=self.hidden_neurons_1, input_shape=(None, self.n_feat), return_sequences=True, dropout=self.dropout_1))
        # This will output (n_hidden_2,)
        model.add(
            LSTM(units=self.hidden_neurons_2, input_shape=(None, self.hidden_neurons_1), return_sequences=False, dropout=self.dropout_2))
        # This will output (n_feat,)
        model.add(Dense(self.n_feat))
        # Modifying the softmax with the `Temperature' parameter
        model.add(Lambda(lambda x: x / 1))
        model.add(Activation('softmax'))
        optimiser = optimizers.Adam(lr=self.learning_rate, beta_1=0.9, beta_2=0.999, epsilon=None, decay=0.0, amsgrad=False)
        model.compile(loss="categorical_crossentropy", optimizer=optimiser)

        self.model = model

    def _hot_encode(self, X):
        """
        This function takes in a list of smiles strings and returns the smiles strings hot encoded split into windows.

        :param X: smiles strings
        :type X: list of strings
        :return: hot encoded smiles string in windows
        :rtype: numpy array of shape (n_samples*n_windows, window_length, n_features)
        """

        if isinstance(self.idx_to_char, type(None)) and isinstance(self.char_to_idx, type(None)):
            all_possible_char = ['G', 'E', 'A']
            max_size = 2

            new_molecules = []
            for molecule in X:
                all_char = list(molecule)

                if len(all_char) + 2 > max_size:
                    max_size = len(all_char) + 2

                unique_char = list(set(all_char))

                for item in unique_char:
                    if not item in all_possible_char:
                        all_possible_char.append(item)

                all_possible_char.sort()

                molecule = 'G' + molecule + 'E'
                new_molecules.append(molecule)

            self.idx_to_char = {idx: char for idx, char in enumerate(all_possible_char)}
            self.char_to_idx = {char: idx for idx, char in enumerate(all_possible_char)}
            n_possible_char = len(self.idx_to_char)
        else:
            new_molecules = []
            for molecule in X:
                molecule = 'G' + molecule + 'E'
                new_molecules.append(molecule)

            n_possible_char = len(self.idx_to_char)

        # if not isinstance(self.smiles, type(None)):
        #     self.smiles = new_molecules
        self.padded_smiles = new_molecules  # These are only padded with 'G' and 'E', not 'A' like for model 2

        # Splitting X into window lengths and y into the characters after each window
        window_X = []
        window_y = []

        self.idx_to_window = []
        counter = 0
        for mol in new_molecules:
            self.idx_to_window.append(counter)
            for i in range(len(mol) - self.window_length):
                window_X.append(mol[i:i+self.window_length])
                window_y.append(mol[i+self.window_length])
                counter += 1

        # One hot encoding
        n_samples = len(window_X)
        n_features = n_possible_char

        X_hot = np.zeros((n_samples, self.window_length, n_features), dtype=np.int32)
        y_hot = np.zeros((n_samples, n_features), dtype=np.int32)

        for n in range(n_samples):
            sample_x = window_X[n]
            sample_x_idx = [self.char_to_idx[char] for char in sample_x]
            input_sequence = np.zeros((self.window_length, n_features))
            for j in range(self.window_length):
                input_sequence[j][sample_x_idx[j]] = 1.0
            X_hot[n] = input_sequence

            output_sequence = np.zeros((n_features,))
            sample_y = window_y[n]
            sample_y_idx = self.char_to_idx[sample_y]
            output_sequence[sample_y_idx] = 1.0
            y_hot[n] = output_sequence

        return X_hot, y_hot

    def _hot_decode(self, X):

        cold_X = []

        n_samples = X.shape[0]
        max_length = X.shape[1]

        for i in range(n_samples):
            smile = ''
            for j in range(max_length):
                out_idx = np.argmax(X[i, j, :])
                smile += self.idx_to_char[out_idx]

            cold_X.append(smile)

        return cold_X

    def _predict(self, X_strings, X_hot, model, temperature, max_length):
        """
        This function takes in a list of smiles strings. Then, it takes the first window from each smiles and predicts
        a full smiles string starting from that window.

        :param X: smiles strings
        :type: list of smiles strings
        :param model: the keras model
        :param temperature: the parameter that changes the softmax
        :param max_length: Maximum length of the strings to be predicted.
        :type max_length: int larger than 0
        :return: predictions
        :rtype: list of strings
        """

        model = self._modify_model_for_predictions(model, temperature)

        n_samples = len(X_strings)

        all_predictions = []

        n_windows = 0
        idx_first_window = 0

        for i in range(0, n_samples):
            idx_first_window += n_windows

            X_pred = X_hot[idx_first_window, :, :]  # predicting from the first window
            X_pred = np.reshape(X_pred, (1, X_pred.shape[0], X_pred.shape[1]))  # shape (1, window_size, n_feat)

            y_pred = X_strings[i][:self.window_length]

            X_pred_temp = np.copy(X_pred)

            while (y_pred[-1] != 'E'):
                out = model.predict(X_pred_temp)  # shape (1, n_feat)
                y_pred += self._hot_decode(np.reshape(out, (1, out.shape[0], out.shape[1])))[0]
                X_pred_temp[:, :-1, :] = X_pred_temp[:, 1:, :]

                y_pred_hot = np.zeros((1, X_pred_temp.shape[-1]))
                y_pred_hot[:, np.argmax(out)] = 1

                X_pred_temp[:, -1, :] = y_pred_hot

                if len(y_pred) == max_length:
                    break

            if y_pred[0] == 'G':
                y_pred = y_pred[1:]
            if y_pred[-1] == 'E':
                y_pred = y_pred[:-1]

            all_predictions.append(y_pred)

            # This is the index of the next 'first window' in X_hot
            n_windows = len(X_strings[i]) - self.window_length

        return all_predictions

    def _idx_to_window_idx(self, idx):
        """
        This function takes the indices of the smiles strings and returns the indices of the corresponding windows.

        :param idx: list of ints
        :return:  list of ints
        """

        window_idx = []

        for i, idx_start in enumerate(idx):
            if idx_start < len(self.idx_to_window)-1:
                w_idx_start = self.idx_to_window[int(idx[i])]
                w_idx_end = self.idx_to_window[int(idx[i])+1]       # idx where the next sample starts
                for j in range(w_idx_start, w_idx_end):
                    window_idx.append(j)
            else:
                w_idx_start = self.idx_to_window[int(idx[i])]
                w_idx_end = self.X_hot.shape[0]
                for j in range(w_idx_start, w_idx_end):
                    window_idx.append(j)

        return window_idx

    def _fit_with_rl(self, temperature, max_length):
        raise NotImplementedError

class Model_2(_Model):
    """
    Estimator Model 2

    This estimator learns from full sequences and can predict new smiles strings starting from any length fragment.

    """

    def __init__(self, tensorboard=False, hidden_neurons_1=256, hidden_neurons_2=256, dropout_1=0.3, dropout_2=0.5,
                 batch_size="auto", epochs=4, smiles=None, learning_rate=0.001):
        """
            This function uses the initialiser of the parent class and initialises the window length.

            :param tensorboard: whether to log progress to tensorboard or not
            :type tensorboard: bool
            :param hidden_neurons_1: number of hidden units in the first LSTM
            :type hidden_neurons_1: int
            :param hidden_neurons_2: number of hidden units in the second LSTM
            :type hidden_neurons_2: int
            :param dropout_1: dropout rate in the first LSTM
            :type dropout_1: float
            :param dropout_2:  dropout rate in the 2nd LSTM
            :type dropout_2: float
            :param batch_size: Size of the data set batches to use during training
            :type batch_size: int
            :param epochs: number of iterations of training
            :type epochs: int
            :param smiles: list of smiles strings from which to learn
            :type smiles: list of strings
            """

        super(Model_2, self).__init__(tensorboard, hidden_neurons_1, hidden_neurons_2, dropout_1, dropout_2,
                                     batch_size, epochs, smiles, learning_rate)

        if not isinstance(self.smiles, type(None)):
            self.X_hot, self.y_hot = self._hot_encode_fitting(smiles)

    def _initialise_data_fit(self, X):
        """
        This function checks whether the smiles strings are stored in the class. Then it checks that X is a list of
        indices specifying which data samples to use. Then, it returns the appropriate smiles strings hot
        encoded.

        :param X: either list of smiles strings or indices.
        :type X: either list of strings or list of ints
        :return: smiles strings hot encoded and the following character
        :rtype: numpy arrays of shape (n_samples, max_length, n_unique characters) and (n_samples, max_length, n_unique_characters)
        """

        if not isinstance(self.smiles, type(None)):
            if not utils.is_positive_integer_or_zero_array(X):
                raise utils.InputError("The indices need to be positive or zero integers.")

            # This line is just so that the indices are ints of the right shape for Osprey
            X = np.reshape(np.asarray(X).astype(np.int32), (np.asarray(X).shape[0], ))

            X_hot = np.asarray([self.X_hot[i] for i in X])
            y_hot = np.asarray([self.y_hot[i] for i in X])
        else:
            X_hot, y_hot = self._hot_encode_fitting(self._check_smiles(X))

        return X_hot, y_hot

    def _initialise_data_predict(self, X, frag_length):
        """
        X can either be a list of smiles strings or the indices to the samples to be used for prediction. In the latter
        case, the data needs to have been stored inside the class.

        This function takes the smiles strings and extract the first few characters (number specified by the parameter
        frag_length). Prediction will start from these few characters.

        :param X: list of smiles or list of indices
        :type X: list of strings or list of ints
        :param frag_length: number of characters of each smiles strings to use for prediction
        :type frag_length: int
        :return: list of the first fragment of each smile string specified and its one-hot encoded version.
        :rtype: list of strings, numpy array of shape (n_samples, frag_length, n_unique_char)
        """

        # TODO add a check that the frag_length is < than the shortest smile
        # Predictions will start from a 'G'
        if isinstance(X, type(None)):
            X_hot = None
            X_strings = None
        # Predictions will start from a fragment of smiles strings stored in the class
        elif not isinstance(self.smiles, type(None)):
            if not utils.is_positive_integer_or_zero_array(X):
                raise utils.InputError("The indices need to be positive or zero integers.")

            # This line is just so that the indices are ints of the right shape for Osprey
            X = np.reshape(np.asarray(X).astype(np.int32), (np.asarray(X).shape[0],))

            X_hot = np.asarray([self.X_hot[i][:frag_length] for i in X])
            X_strings = np.asarray([self.padded_smiles[i][:frag_length] for i in X])
        # Predictions will start from fragments of smiles strings passed through the argument
        else:
            X = self._check_smiles(X)
            X_strings = [item[:frag_length] for item in X]  # No 'G' is added because it is done in the Hot encode function
            X_hot = self._hot_encode_predict(X_strings)
            X_strings = ["G" + item[:frag_length] for item in X] # Now the G is needed since the hot encoded fragments will have it

        return X_strings, X_hot

    def _padd_GEA(self, smiles, max_size):
        """
        This function takes some smiles and appends 'G' and 'E' at the extremities and then adds 'A' to all the smiles
        that are shorter than max_length.

        :param smiles: list of smiles strings
        :param max_size: max length of the smiles strings
        :return: list of padded smiles strings
        """

        new_molecules = []
        for molecule in smiles:
            molecule = 'G' + molecule + 'E'
            if len(molecule) <= max_size:
                padding = int(max_size - len(molecule))
                for i in range(padding):
                    molecule += 'A'
            else:
                raise utils.InputError("One of the smiles exceeds the maximum length of %i." % (max_size))
            new_molecules.append(molecule)

        return new_molecules

    def _onehot_encode(self, padded_smiles, max_size, n_feat):
        """
        This function takes the padded smiles and hot encodes them.

        :param padded_smiles: list of smiles strings that are padded
        :param max_size: the maximum length of the smiles strings
        :param n_feat: the number of characters present in the strings
        :return: two numpy arrays of shape (n_samples, max_size, n_feat) and (n_samples, n_feat)
        """
        n_samples = int(len(padded_smiles))

        X_hot = np.zeros((n_samples, max_size, n_feat), dtype=np.int16)
        y_hot = np.zeros((n_samples, max_size, n_feat), dtype=np.int16)

        for n in range(n_samples):
            sample = padded_smiles[n]
            try:
                sample_idx = [self.char_to_idx[char] for char in sample]
            except KeyError:
                raise utils.InputError(
                    "One of the molecules contains a character that was not present in the first round of training.")
            input_sequence = np.zeros((max_size, n_feat))
            for j in range(max_size):
                input_sequence[j][sample_idx[j]] = 1.0
            X_hot[n] = input_sequence

            output_sequence = np.zeros((max_size, n_feat))
            for j in range(max_size - 1):
                output_sequence[j][sample_idx[j + 1]] = 1.0
            y_hot[n] = output_sequence

        return X_hot, y_hot

    def _hot_encode_fitting(self, X):
        """
        This function hot encodes the smiles for the fit function. When the fit function is called for the first time,
        the strings are padded with 'G', 'A' and 'E' and the idx_to_char dictionaries are created and subsequently used
        for hot encoding. When the fit function is called later, the stings are padded with 'G', 'A' and 'E' and hot
        encoded using the existing idx_to_char dictionaries.

        :param X: the smiles strings hot encoded.
        :return: two numpy arrays of shape (n_samples, max_size, n_feat)
        """

        if isinstance(self.idx_to_char, type(None)) and isinstance(self.char_to_idx, type(None)):
            all_possible_char = ['G', 'E', 'A']
            max_size = 2

            for molecule in X:
                all_char = list(molecule)

                if len(all_char) + 2 > max_size:
                    max_size = len(all_char) + 2

                unique_char = list(set(all_char))
                for item in unique_char:
                    if not item in all_possible_char:
                        all_possible_char.append(item)

            all_possible_char.sort()

            # Padding
            new_molecules = self._padd_GEA(X, max_size)

            self.idx_to_char = {idx: char for idx, char in enumerate(all_possible_char)}
            self.char_to_idx = {char: idx for idx, char in enumerate(all_possible_char)}
            self.max_size = max_size
            n_feat = len(self.idx_to_char)

            X_hot, y_hot = self._onehot_encode(new_molecules, max_size, n_feat)

        else:

            new_molecules = self._padd_GEA(X, self.max_size)

            n_feat = len(self.idx_to_char)

            X_hot, y_hot = self._onehot_encode(new_molecules, self.max_size, n_feat)

        self.padded_smiles = new_molecules

        return X_hot, y_hot

    def _hot_encode_predict(self, X):
        """
        This function takes the smiles fragments that will be used for prediction and adds a 'G' in front of them before
        hot encoding them.

        :param X: list of smiles strings fragments
        :return: list of hot encoded padded fragments of smile string
        """

        new_molecules = []
        max_size = 1
        for molecule in X:
            if len(molecule) + 1 > max_size:
                max_size = len(molecule) + 1
            molecule = "G" + molecule
            new_molecules.append(molecule)

        if self.max_size < max_size:
            raise utils.InputError("The length of a fragment is longer than the maximum length of smiles strings "
                                   "(%i characters)." % (self.max_size))

        n_feat = len(self.idx_to_char)
        n_samples = int(len(new_molecules))

        X_hot = []

        for n in range(n_samples):
            sample = new_molecules[n]
            sample_idx = [self.char_to_idx[char] for char in sample]
            input_sequence = np.zeros((len(sample), n_feat))
            for j in range(len(sample)):
                input_sequence[j][sample_idx[j]] = 1.0
            X_hot.append(input_sequence)

        return X_hot

    def _generate_model(self):
        """
        This function generates the `model 2'.
        :return: None
        """

        model = Sequential()
        # This will output (max_size, n_hidden_1)
        model.add(LSTM(units=self.hidden_neurons_1, input_shape=(None, self.n_feat), return_sequences=True, dropout=self.dropout_1))
        # This will output (max_size, n_hidden_2)
        model.add(
            LSTM(units=self.hidden_neurons_2, input_shape=(None, self.hidden_neurons_1), return_sequences=True, dropout=self.dropout_2))
        # This will output (max_size, n_feat)
        model.add(TimeDistributed(Dense(self.n_feat), input_shape=(None, self.hidden_neurons_2)))
        # Modifying softmax with temperature
        model.add(Lambda(lambda x: x / 1))
        model.add(Activation('softmax'))
        optimiser = optimizers.Adam(lr=self.learning_rate, beta_1=0.9, beta_2=0.999, epsilon=None, decay=0.0,
                                    amsgrad=False)
        model.compile(loss="categorical_crossentropy", optimizer=optimiser)

        self.model = model

    def _predict(self, X_strings, X_hot, model, temperature, max_length, output_probs=False):
        """
        This function either takes in  smiles strings fragments and their hot encoded version, or it takes in nothing
        and generates smiles strings from scratch.

        :param X_strings: Fragment of smiles string or None
        :param X_hot: Hot encoded version of X
        :param model: the model to be used (either the current model or a loaded model)
        :param temperature: the parameter that changes the softmax
        :param max_length: Maximum length of the strings to be predicted.
        :type max_length: int larger than 0
        :param output_probs:
        :type output_probs:
        :return: predictions of smiles strings
        :rtype: list of strings
        """

        if utils.is_none(self.n_feat):
            self.n_feat = len(self.idx_to_char)

        model = self._modify_model_for_predictions(model, temperature)

        experience = []

        if isinstance(X_hot, type(None)):
            # The first character is G
            X_pred = np.zeros((1, max_length, self.n_feat))
            y_pred = 'G'
            X_pred[0, 0, self.char_to_idx['G']] = 1

            for i in range(1, max_length):
                full_out = model.predict(X_pred[:, :i, :])
                out = full_out[0][-1]

                idx_out = np.random.choice(np.arange(self.n_feat), p=out)

                experience.append((X_pred[:, :i, :], full_out))

                X_pred[0, i, idx_out] = 1
                if self.idx_to_char[idx_out] == 'E':
                    break
                else:
                    y_pred += self.idx_to_char[idx_out]

            if y_pred[-1] == 'E':
                y_pred = y_pred[:-1]
            if y_pred[0] == 'G':
                y_pred = y_pred[1:]

            y_pred = re.sub("A", "", y_pred)

            all_predictions = [y_pred]

            if output_probs:
                return all_predictions, experience[-1]
            else:
                return all_predictions
                    
        else:
            n_samples = len(X_hot)

            all_predictions = []

            for n in range(0, n_samples):
                X_frag = X_hot[n]  # shape (fragment_length, n_feat)
                y_pred = X_strings[n]

                while y_pred[-1] != 'E':
                    X_pred = np.reshape(X_frag, (1, X_frag.shape[0], X_frag.shape[1]))  # shape (1, fragment_length, n_feat)

                    full_out = model.predict(X_pred)
                    out = full_out[0][-1]

                    idx_out = np.argmax(out)

                    experience.append((X_pred, full_out))

                    y_pred += self.idx_to_char[idx_out]
                    # X_pred = self._hot_encode([y_pred[1:]])[0][0]

                    X_pred_temp = np.zeros((X_frag.shape[0]+1, X_frag.shape[1]))
                    X_pred_temp[:-1] = X_frag
                    X_pred_temp[-1][idx_out] = 1
                    X_frag = X_pred_temp

                    if len(y_pred) == 100:
                        break

                if y_pred[-1] == 'E':
                    y_pred = y_pred[:-1]
                if y_pred[0] == 'G':
                    y_pred = y_pred[1:]
                y_pred = re.sub("A", "", y_pred)
                all_predictions.append(y_pred)

            if output_probs:
                return all_predictions, experience[-1]
            else:
                return all_predictions

    def _fit_with_rl(self, n_train_episodes, temperature, max_length):
        """
        This function fits the model using reinforcement learning.

        :param temperature: Temperature factor in the softmax
        :type temperature: positive float
        :param max_length: maximum length of an episode
        :type max_length: int
        :return:
        :rtype:
        """

        # Keeping a model for the 'prior' and making an 'agent' model where one can differentiate the new cost function with respect to the weights
        if utils.is_none(self.model):
            model_prior = self._modify_model_for_predictions(self.loaded_prior, temperature)
            model_agent = self._modify_model_for_predictions(self.loaded_model, temperature)
        else:
            self.save("prior_model")
            self.load("prior_model")
            model_prior = self._modify_model_for_predictions(self.loaded_prior, temperature)
            model_agent = self._modify_model_for_predictions(self.loaded_model, temperature)

        # Making the Reinforcement Learning training function
        training_function = self._generate_rl_training_fn(model_agent)

        # The training function takes as arguments: the state, the action and the reward.
        # These have to be calculated in advance and stored.
        experience = []
        rewards = []

        #TODO understand if modifying the model after generating the RL function is a problem
        # This generates some episodes
        for ep in range(int(n_train_episodes/10)):

            # Generating 30 episodes and keeping the 15 with highest score
            for n in range(30):
                # Using the agent network to predict a smile
                # prediction is the smile
                # exp_i is a tuple with the hot-encoded smile and the probability distributions of the actions taken at each time step
                prediction, exp_i = self._predict(X_strings=None, X_hot=None, model=model_agent, max_length=max_length,
                                                        output_probs=True, temperature=temperature)

                # Hot encoded smile
                state_i = exp_i[0]

                # Calculate the sequence log-likelihood for the prior
                prior_action_prob = model_prior.predict(state_i)
                individual_action_probability = np.sum(np.multiply(state_i[:, 1:], prior_action_prob[:, :-1]), axis=-1)
                prod_individual_action_prob = np.prod(individual_action_probability)
                sequence_log_likelihood_i = np.log(prod_individual_action_prob)

                # Calculate the reward for the finished smile
                reward_i = self._calculate_reward(prediction[0])

                # In case the predicted smile was invalid
                if utils.is_none(reward_i):
                    continue

                # Adding the episode to the experience memory
                an_experience = (state_i, sequence_log_likelihood_i, reward_i)

                # Keeping the experiences with the highest reward
                if len(experience) < 15:
                    experience.append(an_experience)
                    rewards.append(reward_i)
                else:
                    # If the minimum reward is smaller than the reward for the current smile, replace it
                    min_reward = min(rewards)
                    if min_reward < reward_i:
                        ind_to_pop = np.argmin(rewards)
                        del experience[ind_to_pop]
                        del rewards[ind_to_pop]
                        experience.append(an_experience)
                        rewards.append(reward_i)

            shuffle(experience)

            # Training over random samples from the experience
            for _ in range(10):
                random_n = random.randint(0, len(experience)-1)
                state = experience[random_n][0]
                prior_loglikelihood = experience[random_n][1]
                reward = experience[random_n][2]

                training_function([state, prior_loglikelihood, reward])





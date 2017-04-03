import numpy as np
import os
from scipy import special
import itertools

class actor_critic:

    def __init__(self, dim_theta=6, d=47):

        self.dim_theta = dim_theta
        # initialize theta as random column vector, entries [0,1)
        self.theta = np.random.rand(dim_theta, 1)

        # initialize weight vector (column) for value function approximation
        self.w = self.init_w(d)

        # number of topics
        self.d = d

        # d x d x dim_theta tensor, computed within sample_action and used for
        # calculating gradient for theta update
        self.tensor_phi = np.zeros([self.d, self.d, self.dim_theta])        

        # d x d matrix, computed within sample_action and used for sampling action P
        # and also for calculating gradient for theta update
        self.mat_alpha = np.zeros([self.d, self.d])

    def init_w(self, d):
        """
        Input:
        d - number of topics

        Feature vector is 
        [1, pi_1,...,pi_d, pi_1*pi_1,...,pi_1*pi_d, pi_2*pi_2,...,pi_2*pi_d, ...... , pi_d*pi_d]
        Initialize weight vector for value function approximation
        Need to decide whether to include the null topic
        """
        num_features = int((d+1)*d / 2 + d + 1)
        return np.random.rand(num_features, 1)


    def init_pi0(self, path_to_dir='/home/t3500/devdata/mfg/distribution/train_reordered'):
        """
        Generates the collection of initial population distributions.
        This collection will be sampled to get the start state for each training episode
        Assumes that each file in director has rows of the format:
        pi^0_1, ... , pi^0_d
        where d is a fixed constant across all files
        """
        list_pi0 = []
        for filename in os.listdir(path_to_dir):
            path_to_file = path_to_dir + '/' + filename
            f = open(path_to_file, 'r')
            list_lines = f.readlines()
            f.close()
            # Ignore the null topic (need to make a decision later)
            list_pi0.append( list(map(int, list_lines[0].strip().split(',')))[1:1+self.d] )
            
        num_rows = len(list_pi0)
        num_cols = len(list_pi0[0])

        self.mat_pi0 = np.zeros([num_rows, num_cols])
        for i in range(len(list_pi0)):
            total = np.sum(list_pi0[i])
            self.mat_pi0[i] = list(map(lambda x: x/total, list_pi0[i]))
        

    def reorder(self, list_rows):
        """
        Given a list of rows (each is a pi^n), order all rows by decreasing popularity
        based on the first row.
        """
        row1 = list_rows[0]
        # create mapping from index to value
        list_pairs = []
        for i in range(len(row1)):
            list_pairs.append( (i, row1[i]) )

        # sort by decreasing popularity
        list_pairs.sort(reverse=True, key=lambda x: x[1])

        # extract ordering
        order = []
        for pair in list_pairs:
            order.append( pair[0] )
        
        # apply ordering to all rows in list_rows
        for i in range(len(list_rows)):
            list_rows[i] = [ list_rows[i][j] for j in order ]

        return list_rows

    
    def reorder_files(self, path_to_dir='/home/t3500/devdata/mfg/distribution/train', output_dir='/home/t3500/devdata/mfg/distribution/train_reordered'):
        """
        Process all files in given directory, creates new files
        """
        for filename in os.listdir(path_to_dir):
            path_to_file = path_to_dir + '/' + filename
            f = open(path_to_file, 'r')
            f.readline() # skip the header line of topics
            list_lines = f.readlines()
            f.close()
            # strip away newline, convert csv format to list of entries,
            # remove the last empty entry (due to extra comma)
            list_lines = list(map(lambda x: x.strip().split(',')[:-1], list_lines))
            # convert to int
            for i in range(len(list_lines)):
                list_lines[i] = list(map(int, list_lines[i]))
            # reorder
            list_rows = self.reorder(list_lines)
            # write to new file
            index_dot = filename.index('.')
            filename_new = filename[:index_dot] + '_reordered' + filename[index_dot:]
            f = open(output_dir + '/' + filename_new, 'w')
            for row in list_rows:
                s = ','.join(map(str, row))
                s += '\n'
                f.write(s)
            f.close()


    def sample_action(self, pi):
        """
        Samples from product of d d-dimensional Dirichlet distributions
        Input:
        pi - row vector
        Returns an entire transition probability matrix
        """
        # Construct all alphas
        self.mat_alpha = np.zeros([self.d, self.d])
        # Create tensor phi(i,j,pi) for storing all phi matrices for later use
        self.tensor_phi = np.zeros([self.d,self.d,self.dim_theta])
        for i in range(self.d):
            # d x (num_features) matrix
            mat_phi = np.zeros([self.d, self.dim_theta])
            # each row is phi(i, j, pi)
            for j in range(self.d):
                # construct feature vector, (num_features) x 1
                phi = [1, pi[i], pi[j], pi[i]*pi[j], pi[i]**2, pi[j]**2]
                # insert into mat_phi
                mat_phi[j] = phi
            # Store phi matrix into tensor_phi
            self.tensor_phi[i] = mat_phi
            temp = mat_phi.dot(self.theta) # d x 1
            # element-wise product, to get all entries nonzero
            alpha = temp * temp # d x 1
            # Insert check for zero
            for element in alpha:
                if element <= 0:
                    print("Error! element of alpha is non-positive!")
            # Insert alpha transpose into mat_alpha as the i-th row
            self.mat_alpha[i] = np.transpose(alpha)
        
        # Sample matrix P from Dirichlet
        P = np.zeros([self.d, self.d])
        for i in range(self.d):
            # Get y^i_1, ... y^i_d
            y = [np.random.gamma(shape=a, scale=1) for a in self.mat_alpha[i, :]]
            total = np.sum(y)
            # Store into i-th row of matrix P
            P[i] = [y_j/total for y_j in y]

        return P


    def calc_cost(self, P, pi, d):
        """
        Input:
        P - transition matrix
        pi - population distribution as row vector
        d - should be self.d always, except during testing

        R = \sum_i pi_i \sum_j P_{ij} c_{ij}(pi, P_i)
        Using c_{ij}(pi, P_i) = P_{ij}(pi_i - pi_j), this becomes
        R = \sum_i pi_i \sum_j (P_{ij})^2 (pi_i - pi_j)
        R = < pi, v > where v is a vector whose elements are
        v_i = \sum_j (P_{ij})^2 (pi_i - pi_j)
             = [ (P_{i1})^2 , ... , (P_{id})^2 ] dot [(pi_i - pi_1), ..., (pi_i - pi_d)]
        """
        # Create vector v
        v = np.zeros([d, 1])
        for i in range(d):
            v1 = P[i, :] * P[i, :] # element-wise multiplication
            v2 = pi[i] * np.ones(d) - pi
            v[i] = v1.dot(v2)
        reward = pi.dot(v)

        return reward


    def calc_value(self, pi):
        """
        Input:
        pi - population distribution as a row vector

        Returns V(pi; w) = varphi(pi) dot self.w
        where varphi(pi) is the feature vector constructed using pi
        """
        # generate pairs of (pi_i, pi_j) for all i, for all j >= i
        list_tuples = list(itertools.combinations_with_replacement(pi, 2))
        # calculate products
        list_features = []
        for idx in range(len(list_tuples)):
            pair = list_tuples[idx]
            list_features.append(pair[0] * pair[1])
        # append first-order feature
        list_features = list_features + list(pi)
        # append bias
        list_features.append(1)
        # calculate value by inner product
        value = np.array(list_features).dot(self.w)

        return value


    def calc_features(self, pi):
        """
        Input:
        pi - population distribution as a row vector

        Returns varphi(pi) as a row vector
        """        
        # generate pairs of (pi_i, pi_j) for all i, for all j >= i
        list_tuples = list(itertools.combinations_with_replacement(pi, 2))
        # calculate products
        list_features = []
        for idx in range(len(list_tuples)):
            pair = list_tuples[idx]
            list_features.append(pair[0] * pair[1])
        # append first-order feature
        list_features = list_features + list(pi)
        # append bias
        list_features.append(1)

        return np.array(list_features)


    def calc_gradient(self, P, pi):
        """
        Input:
        P - transition probability matrix
        pi - population distribution as a row vector

        Calculates \nabla_{theta} log (F(P, pi, theta))
        where F is the product of d d-dimensional Dirichlet distributions

        tensor_phi and mat_alpha are global variables computed in sample_action()
        """
        # initialize gradient as column vector
        gradient = np.zeros([self.dim_theta, 1])

        for i in range(self.d):

            # psi(\sum_j alpha^i_j)
            multiplier = special.digamma( np.sum(self.mat_alpha[i]) )

            for j in range(self.d):
                # 2 * (phi(i,j,pi) dot theta) phi(i,j,pi)
                common_term = 2 * (self.tensor_phi[i,j].dot(self.theta)) * np.transpose(self.tensor_phi[i, j:j+1, :])
                
                # first term = - \nabla log(\Gamma(\alpha^i_j))
                # = - psi(alpha^i_j) * 2 * (phi(i,j,pi) dot theta) phi(i,j,pi)
                first_term = - special.digamma(self.mat_alpha[i,j]) * common_term

                # second term = psi(\sum_j alpha^i_j) * \nabla \alpha^i_j
                # = psi(\sum_j \alpha^i_j) * 2 * (phi(i,j,pi) dot theta) phi(i,j,pi)
                second_term = multiplier * common_term

                # third term = \nabla (\alpha^i_j - 1) log(P_{ij})
                # = 2 * (phi(i,j,pi) dot theta) phi(i,j,pi) * log(P_{ij})
                third_term = np.log( P[i,j] ) * common_term

                gradient = gradient + first_term + second_term + third_term

        return gradient


    def train(self, num_episodes=4000, gamma=0.99, lr_critic=0.2, lr_actor=0.6, consecutive=100):
        """
        Input:
        1. num_episodes - each episode is 16 steps (9am to 12midnight)
        2. gamma - temporal discount
        3. lr_critic - learning rate for value function parameter update
        4. lr_actor - learning rate for policy parameter update
        5. consecutive - number of consecutive episodes for each reporting of average cost

        Main actor-critic training procedure that improves theta and w
        """

        # initialize collection of start states
        self.init_pi0(path_to_dir=r'C:\Users\Jiachen\Documents\Projects\Python\RL\MFG\data_train_reordered')
        self.num_start_samples = self.mat_pi0.shape[0] # number of rows

        list_cost = []
        for episode in range(num_episodes):
            print("Episode", episode)
            # Sample starting pi^0 from mat_pi0
            idx_row = np.random.randint(self.num_start_samples)
            pi = self.mat_pi0[idx_row, :] # row vector

            discount = 1
            total_cost = 0
            num_steps = 0

            # Stop after finishing the iteration when num_steps=15, because
            # at that point pi_next = the predicted distribution at midnight
            while num_steps < 15:
                num_steps += 1

                print("pi\n", pi)

                # Sample action
                P = self.sample_action(pi)
            
                # Take action, get pi^{n+1} = P^T pi
                pi_next = np.transpose(P).dot(pi)

                cost = self.calc_cost(P, pi, self.d)
                
                # Calculate TD error
                vec_features_next = self.calc_features(pi_next)
                vec_features = self.calc_features(pi)
                # Consider using the terminal condition V^N = 0
                delta = cost + gamma*(vec_features_next.dot(self.w)) - (vec_features.dot(self.w))

                # Update value function parameter
                # w <- w + alpha * delta * varphi(pi)
                # still a column vector
                length = len(vec_features)
                self.w = self.w + lr_critic * delta * np.transpose(vec_features.reshape(1,length))

                # theta update
                gradient = self.calc_gradient(P, pi)
                self.theta = self.theta - lr_actor * delta * gradient

                discount = discount * gamma
                pi = pi_next
                total_cost += cost

            list_cost.append(total_cost)

            if (episode % consecutive == 0):
                print("Theta\n", self.theta)
                print("pi\n", pi)
                print("Average cost during previous %d episodes: " % consecutive, str(sum(list_cost)/consecutive))
                list_cost = []
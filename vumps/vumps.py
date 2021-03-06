import constants
import pinv_manual
from ncon import ncon
import numpy as np
from scipy import linalg
from scipy.sparse.linalg import eigs
from scipy.sparse.linalg import eigsh
from scipy.sparse.linalg import LinearOperator
from scipy.sparse.linalg import bicgstab
# from scipy.sparse.linalg import bicg
import matplotlib.pyplot as plt
import copy


'''
Index Ordering Convention
   
   0--A--2   0--A_L--2   2--A_R--0  0--Ac--2
      |          |           |         |
      1          1           1         1
                                                             2   
 ---1    1---                   3--A_L--1   1--A_R--3        |
 |          |                       |           |         0--W--1
 L          R       0--C--1         |           |            |
 |          |                   2--A_L--0   0--A_R--2        3
 ---0    0---
Four sections:
1.Functions that will be used for both 2sites and MPO
2.Functions only for 2sites VUMPS
3.Functions only for MPO VUMPS
4.Excitation
'''

'''
########################################################################################################################
Section 1 Functions that will be used for both 2sites and MPO
Contain three parts:
1.Change uMPS to canonical form.
2.Find {A_L, A_R} from a given {Ac, C} 
3.Sum infinite transfer matrix (most FREQUENTLY used) 
########################################################################################################################

###########################################################
Part 1-1
Change uMPS to canonical form: method 1
See Algorithm 1 & 2 in arXiv:1810.07006v3
This method seems to be unstable, and doesn't been used now.
For impatience, just SKIP this part
###########################################################
'''

def left_orthonormalize(A, L0, eta=1e-10):
    '''
    Algorithm 1: Gauge transform a uniform MPS A into left-orthogonal form
    0--L--1 0--A--2 ----> 0--A_L--2  0--L--1
               |     QR      |
               1             1
    '''
    print('left_orthonormalize begin!')
    D,d,_ = A.shape
    def transfer_map(X):
        '''
        1--- --A--(-2)           ----1
        |     |                 |
        x     |3        ----->  x
        |     |                 |
        2--- --A_L--(-1)         ----0
        '''
        X = X.reshape(D,D)
        X_out = ncon([X,A,np.conj(A_L)],
                     [[2,1], [1,3,-2], [2,3,-1]])
        return X_out.reshape(D*D)

    L = L0 / linalg.norm(L0)
    L_old = L
    ## QR
    LA = ncon([L,A],
              [[-1,1],[1,-2,-3]])
    A_L, L = linalg.qr(LA.reshape(D*d,D))
    A_L = A_L.reshape(D,d,D)
    lam = linalg.norm(L); L = L / lam
    delta = linalg.norm(L + L_old)
    print('delta = ', delta)
    while not (delta < eta or abs(delta-2) < eta):
        ## Arnoldi
        L = L.reshape(-1)
        _, L = eigs(LinearOperator((D**2, D**2), matvec=transfer_map), k=1, which='LM',
                    v0=L, tol=eta / 10)
        L = L.reshape(D,D)
        _,L = linalg.qr(L)
        L = L / linalg.norm(L)
        L_old = L
        LA = ncon([L, A],
                  [[-1, 1], [1, - 2, -3]])
        A_L, L = linalg.qr(LA.reshape(D * d, D))
        A_L = A_L.reshape(D, d, D)
        lam = linalg.norm(L); L = L/lam;
        delta = linalg.norm(L + L_old)
        print('delta = ', delta)
    return A_L, L, lam

def right_orthonormalize(A, R0, eta=1e-10):
    '''
    Algorithm 1: Gauge transform a uniform MPS A into right-orthogonal form
    0--A--2  1--R--0           1--R--0  2--A_R--0
       |               ----->               |
       1                 QR                 1
    '''
    print('right_orthonormalize begin!')
    D,d,_ = A.shape
    def transfer_map(X):
        X = X.reshape(D,D)
        X_out = ncon([X,A,np.conj(A_R)],
                     [[2,1], [-2,3,1], [2,3,-1]])
        return X_out.reshape(D*D)

    R = R0 / linalg.norm(R0)
    R_old = copy.deepcopy(R)
    ## QR
    RA = ncon([R,A],
              [[-1,1],[-3,-2,1]])
    A_R, R = linalg.qr(RA.reshape(D*d,D))
    A_R = A_R.reshape(D,d,D)
    lam = linalg.norm(R); R = R / lam
    delta = linalg.norm(R - R_old)
    print('delta = ', delta)
    while not (delta < eta or abs(delta-2) < eta):
        ## Arnoldi
        R = R.reshape(-1)
        _, R = eigs(LinearOperator((D**2, D**2), matvec=transfer_map), k=1, which='LM',
                    v0=R, tol=eta/10 )
        R = R.reshape(D,D)
        _,R = linalg.qr(R)
        R = R / linalg.norm(R)
        R_old = copy.deepcopy(R)
        RA = ncon([R, A],
                  [[-1, 1], [-3,-2,1]])
        A_R, R = linalg.qr(RA.reshape(D * d, D))
        A_R = A_R.reshape(D, d, D)
        lam = linalg.norm(R);
        R = R / lam
        delta = linalg.norm(R - R_old)
        print('delta = ', delta)
    return A_R, R, lam

def mixed_canonical(A, eta = 1e-10):
    A_L, _, lam = left_orthonormalize(A,L0,eta)
    A_R, C, _ = right_orthonormalize(A_L,R0,eta)
    U,C,V_dagger = linalg.svd(C, full_matrices=False)
    A_L = ncon([np.conj(U.T), A_L, U],
               [[-1,1], [1,-2,2], [2,-3]])
    V = np.conj(V_dagger.T)
    A_R = ncon([V_dagger, A_R, V],
               [[-3,1], [2,-2,1], [2,-1]])
    return A_L,A_R, np.diag(C), lam

'''
########################################################
Part 1-2
Change uMPS to canonical form: method 2
Ref: R. Orús and G. Vidal. PRB78,155117(2008)􏱮
Three functions:
1.A_to_lam_gamma
2.lam_gamma_to_canonical
3.canonical_to_Al_Ar
>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
The final result we want is A_L, A_R, and C
Ac should be calculate using (A_L,C) or (C,A_R)
For instance, most of the time, we use
lam, gamma = A_to_lam_gamma(A)
lam, gamma = lam_gamma_to_canonical(lam, gamma)
A_L, A_R = canonical_to_Al_Ar(lam, gamma)
C = lam
Ac = ncon([A_L, C],
          [[-1, -2, 1], [1, -3]])
########################################################
'''
def A_to_lam_gamma(A):
    '''
    A = U@S@V_da
    return (lam = S; gama = V_da@U)
    '''
    D,d, _ = A.shape
    u,s,v_da = linalg.svd(A.reshape(D*d,D), full_matrices=False)
    lam = np.diag(s)/linalg.norm(s)
    u = u.reshape(D,d,D)
    gamma = ncon([v_da, u],
                 [[-1,1], [1,-2,-3]])
    norm = ncon([lam@lam, gamma, lam@lam, np.conj(gamma)],
                [[1,4], [1,3,2], [2,5], [4,3,5]])**0.5
    gamma = gamma/norm
    return lam, gamma


def lam_gamma_to_canonical(lam, gamma):
    '''
    Get (lam,gamma) to canonical (lam,gamma)
    '''
    def get_L_or_R(l):
        dtemp, utemp = linalg.eigh(l)
        dtemp = abs(dtemp)
        # chitemp = sum(dtemp > dtol)
        chitemp = len(dtemp)
        d = np.diag(dtemp[-1:-(chitemp + 1):-1])
        U_da = np.conj(utemp[:, -1:-(chitemp + 1):-1].T)
        L = np.sqrt(d) @ U_da
        return L
    def transfer_map_l(l):
        l = l.reshape(D,D)
        l_out = ncon([l,lam,gamma,np.conj(lam),np.conj(gamma)],
                     [[3,1],[1,2],[2,5,-2],[3,4],[4,5,-1]])
        return l_out
    def transfer_map_r(r):
        r = r.reshape(D,D)
        r_out = ncon([gamma,lam,np.conj(gamma), np.conj(lam), r],
                     [[-2,1,2], [2,3],[-1,1,4],[4,5],[5,3]])
        return r_out
    D,d,_ = gamma.shape
    l0 = np.random.rand(D,D)
    l0 = l0.reshape(-1)
    norm1, l = eigs(LinearOperator((D ** 2, D ** 2), matvec=transfer_map_l), k=1, which='LM',
                v0=l0)
    # print('norm = ', norm1[0])
    l = l.reshape(D,D)
    r0 = np.random.rand(D, D)
    r0 = r0.reshape(-1)
    norm2, r = eigs(LinearOperator((D ** 2, D ** 2), matvec=transfer_map_r), k=1, which='LM',
                v0=r0)
    r = r.reshape(D, D)

    L = get_L_or_R(l)
    R = get_L_or_R(r)

    u_tmp,s_tmp,vda_tmp = linalg.svd(L@lam@R.T, full_matrices=False)
    lam_new = np.diag(s_tmp)

    gamma_new = ncon([vda_tmp@linalg.inv(R.T), gamma, linalg.inv(L)@u_tmp],
                     [[-1,1], [1,-2,2], [2,-3]])
    lam_new = lam_new/linalg.norm(lam_new)
    norm = ncon([lam_new@lam_new, gamma_new, lam_new@lam_new, np.conj(gamma_new)],
                [[1,4], [1,3,2], [2,5], [4,3,5]])**0.5
    gamma_new = gamma_new/norm
    return lam_new, gamma_new
def canonical_to_Al_Ar(lam, gamma):
    A_L = ncon([lam, gamma],
               [[-1,1], [1,-2,-3]])
    A_R = ncon([gamma, lam],
               [[-3,-2,1], [1,-1]])
    return A_L, A_R

'''
##########################################################
Part 2
Find {A_L, A_R} from a given {Ac, C} 
Ref: Algorithm 5 in arXiv:1810.07006v3
##########################################################
'''
def min_Ac_C(Ac, C):
    D,d,_ = Ac.shape

    U_Ac,S_Ac,V_dagger_Ac = linalg.svd(Ac.reshape(D*d,D), full_matrices=False)
    U_c, S_c, V_dagger_c = linalg.svd(C, full_matrices=False)
    A_L = (U_Ac@V_dagger_Ac)@np.conj(U_c@V_dagger_c).T
    A_L = A_L.reshape(D,d,D)
    Ac_r = Ac.transpose([2,1,0])

    C_r = C.T
    U_Ac, S_Ac, V_dagger_Ac = linalg.svd(Ac_r.reshape(D * d, D), full_matrices=False)
    U_c, S_c, V_dagger_c = linalg.svd(C_r, full_matrices=False)
    A_R = (U_Ac@V_dagger_Ac)@np.conj(U_c@V_dagger_c).T
    A_R = A_R.reshape(D,d,D)

    '''u_l_ac, _ = linalg.polar(Ac.reshape(D * d, D), side='left')
    u_l_c, _ = linalg.polar(C, side='left')

    al_tilda = u_l_ac @ np.conj(u_l_c).T
    al_tilda = al_tilda.reshape(D, d, D)

    print('left test:', linalg.norm(al_tilda - A_L))

    u_r_ac, _ = linalg.polar(Ac.reshape(D, D * d), side='right')
    u_r_c, _ = linalg.polar(C, side='right')

    ar_tilda = np.conj(u_r_c).T @ u_r_ac
    ar_tilda = ar_tilda.reshape(D, d, D)
    ar_tilda = ar_tilda.transpose([2, 1, 0])

    print('right test:', linalg.norm(ar_tilda - A_R))

    return al_tilda, ar_tilda'''
    return A_L, A_R


'''
########################################################################################################################
Section 2 Functions only for 2sites VUMPS
Three parts:
1. Evaluate 2sites Energy 
2. Get h_L and h_R (will be used as the input of sum_right_left)
3. Final Algorithm for 2sites VUMPS
########################################################################################################################

##########################################################
Evaluate 2sites Energy
##########################################################
'''
def evaluate_energy_two_sites(A_L, A_R, Ac, h):
    e1 = ncon([A_L,Ac,h,np.conj(A_L), np.conj(Ac)],
              [[1,4,2],[2,5,3],[4,5,6,7],[1,6,8],[8,7,3]])
    e2 = ncon([Ac, A_R,h,np.conj(Ac), np.conj(A_R)],
              [[1,4,2],[3,5,2],[4,5,6,7],[1,6,8],[3,7,8]])
    e = (e1+e2)/2
    # print('abs(e-e1) = ', abs(e-e1))
    if abs(e-e1) > 1e-4:
        pass
        # print('e1 is not close to e2 !')
        # print('abs(e-e1) = ', abs(e - e1))
    return e
'''
##########################################################
Get h_L and h_R (will be used as the input of sum_right_left)
##########################################################
'''

def Al_h_to_hL(A_L, h): ## eqn(133) in arXiv:1810.07006v3
    h_L = ncon([A_L,A_L,h,np.conj(A_L), np.conj(A_L)],
              [[1,3,2],[2,4,-2],[3,4,5,6],[1,5,7],[7,6,-1]])
    return h_L

def Ar_h_to_h_R(A_R, h): ## eqn(133) in arXiv:1810.07006v3
    h_R = ncon([A_R, A_R, h, np.conj(A_R), np.conj(A_R)],
               [[2,3,-2],[1,4,2],[3,4,5,6],[7,5,-1],[1,6,7]])
    return h_R

def A_to_Tm(A_L):
    T_L = ncon([A_L, np.conj(A_L)],
               [[-4,1,-2], [-3,1,-1]])
    return T_L

'''
############################################################
Final Algorithm for 2sites VUMPS
This function will largely use the previos defined functions
Ref: Algorithm 4 in arXiv:1810.07006v3
############################################################
'''
def vumps_2sites(h, A, eta=1e-7, pinv = 'scipy'):
    print('>' * 100)
    print('VUMPS for two sites begin!')
    def map_Hac(Ac): ## eqn(131) in arXiv:1810.07006v3
        Ac = Ac.reshape(D,d,D)
        term1 = ncon([A_L,Ac,h_tilda,np.conj(A_L)],
                     [[5,2,1],[1,3,-3],[2,3,4,-2],[5,4,-1]])
        term2 = ncon([Ac, A_R,h_tilda,np.conj(A_R)],
                     [[-1,2,1],[5,3,1],[2,3,-2,4],[5,4,-3]])
        term3 = ncon([L_h,Ac],
                     [[-1,1],[1,-2,-3]])
        term4 = ncon([Ac,R_h],
                     [[-1,-2,1],[-3,1]])
        final = term1+term2+term3+term4
        return final.reshape(-1)
    def map_Hc(C): ## eqn(132) in arXiv:1810.07006v3
        C = C.reshape(D,D)
        term1 = ncon([A_L,C,A_R,h_tilda,np.conj(A_L),np.conj(A_R)],
                     [[1,5,2],[2,3],[4,6,3],[5,6,7,8],[1,7,-1],[4,8,-2]])
        term2 = L_h@C
        term3 = C@R_h.T
        final = term1+term2+term3
        return final.reshape(-1)
    D,d,_ = A.shape
    lam, gamma = A_to_lam_gamma(A)
    lam, gamma = lam_gamma_to_canonical(lam, gamma)
    A_L, A_R = canonical_to_Al_Ar(lam, gamma)
    C = lam
    Ac = ncon([A_L, C],
              [[-1, -2, 1], [1, -3]])
    delta = eta*1000
    e_memory = -1
    e = 0
    count = 0
    while (delta > eta and abs(e - e_memory) > eta / 10) or count <15:
        e_memory = e
        e = evaluate_energy_two_sites(A_L, A_R, Ac, h)
        e_eye = e * np.eye(d ** 2, d ** 2).reshape(d, d, d, d)
        h_tilda = h - e_eye
        # h_tilda = h
        h_L = Al_h_to_hL(A_L, h_tilda)
        h_R = Ar_h_to_h_R(A_R, h_tilda)
        if pinv == 'scipy':
            T_L = A_to_Tm(A_L)
            T_R = A_to_Tm(A_R)
            mat_TL = T_L.reshape(D**2,D**2)
            mat_TR = T_R.reshape(D**2,D**2)
            mat_eye = np.eye(D**2,D**2)
            inv_TL = linalg.pinv(mat_eye-mat_TL).reshape(D,D,D,D)
            inv_TR = linalg.pinv(mat_eye-mat_TR).reshape(D,D,D,D)
            L_h = ncon([inv_TL, h_L],
                       [[-1,-2,1,2], [1,2]])
            R_h = ncon([inv_TR, h_R],
                       [[-1,-2,1,2], [1,2]])
        # L_h = sum_left(h_L, A_L, C,tol=delta/10)
        else:
            C_r = C.T
            L_h = pinv_manual.sum_right_left(h_L, A_L, C_r, tol=delta / 10)
            R_h = pinv_manual.sum_right_left(h_R, A_R, C, tol=delta / 10)
        # print('linalg.norm(R_h-R_h.T)', linalg.norm(R_h-np.conj(R_h.T)))
        # print('R_h = ', R_h)
        # exit()
        # print(Ac.shape)
        E_Ac, Ac = eigs(LinearOperator((D ** 2*d, D ** 2*d), matvec=map_Hac), k=1, which='SR',
                v0=Ac.reshape(-1), tol=delta/10)
        Ac= Ac.reshape(D,d,D)
        E_C, C = eigs(LinearOperator((D ** 2 , D ** 2 ), matvec=map_Hc), k=1, which='SR',
                     v0=C.reshape(-1), tol=delta/10)
        C = C.reshape(D,D)
        A_L, A_R = min_Ac_C(Ac,C)
        Al_C =  ncon([A_L, C],
                    [[-1, -2, 1], [1, -3]])
        delta = linalg.norm(Ac-Al_C)

        if count%5 == 0:
            print(50*'-'+'steps',count, 50*'-')
            print('energy = ', e)
            print('delta = ', delta)
            print('Eac = ', E_Ac)
            print('Ec = ',E_C)
            # print('Eac/Ec', E_Ac/E_C)
        count += 1
    print(50*'-'+' final '+50*'-')
    print('energy = ', e)
    return e, A_L, A_R, Ac, C, L_h, R_h
        # exit()

'''
########################################################################################################################
Section 3 Functions only for MPO VUMPS
Two parts:
1. Construct left and right fixed points of MPO
2. Final Algorithm for MPO VUMPS
########################################################################################################################
##########################################################
Construct left and right fixed points of MPO
Note that it only includes MPO with no long-range interaction,
which means W[a,a] = 0 except for W[0,0] and W[d_w-1,d_w-1]
Ref: Algorithm 6 in PRB 97, 045145 (2018)
##########################################################
'''
def Al_O_to_T_O(A_L, O):
    T_O = ncon([A_L, O, np.conj(A_L)],
               [[-4,1,-2], [1,2],[-3,2,-1]])
    return T_O
def get_Lh_Rh_mpo(A_L, A_R, C,W):
    d_w,_,_,_ = W.shape
    D,d,_ = A_L.shape
    L_W = np.zeros([d_w, D,D], dtype=complex)
    L_W[d_w-1] = np.eye(D,D)
    for i in range(d_w-2,-1,-1): # dw-2,dw-3,...,1,0
        for j in range(i+1, d_w): # j>i: i+1,...d_w-1
            # print(i,j)
            L_W[i] += ncon([L_W[j], Al_O_to_T_O(A_L, W[j, i])],
                           [[1,2],[-1,-2,1,2]]) # Lw[i] = Lw[j]T[j,i]
    C_r = C.T
    # exit()
    R = ncon([np.conj(C_r), C_r],
             [[1, -1], [1, -2]])
    e_Lw = ncon([R, L_W[0]], ## eqn (C27) in PRB 97, 045145 (2018)
                     [[1, 2], [1, 2]])
    # print('e_test_Lw = ', e_test_Lw)
    e_Lw_eye = e_Lw*np.eye(D,D)
    L_W[0] -= e_Lw_eye
    L_W[0] = pinv_manual.sum_right_left(L_W[0], A_L, C_r)

    L_W = L_W.transpose([1,0,2])
    R_W = np.zeros([d_w, D,D], dtype=complex)
    R_W[0] = np.eye(D,D)
    for i in range (1,d_w): # 1,2,...,dw-1
        for j in range(i-1,-1,-1): # j<i: i-1,i-2,...,0
            # print('i=',i,'j=',j)
            R_W[i] += ncon([R_W[j], Al_O_to_T_O(A_R, W[i, j])],
                           [[1,2], [-1,-2,1,2]]) # Rw[i] = T[i,j]R[j]
    # exit()
    L = ncon([np.conj(C), C],
             [[1,-1],[1,-2]])
    e_Rw = ncon([L, R_W[d_w-1]], ## eqn (C27) in PRB 97, 045145 (2018)
                      [[1,2],[1,2]])
    e_Rw_eye = e_Rw * np.eye(D, D)
    # print('e_test_Rw = ', e_test_Rw)
    R_W[d_w - 1] -= e_Rw_eye
    R_W[d_w-1] = pinv_manual.sum_right_left(R_W[d_w-1], A_R, C)

    R_W = R_W.transpose([1,0,2])
    # print(e_Rw, e_Lw)
    return L_W, R_W, (e_Lw+e_Rw)/2
'''
##############################################################
Final Algorithm for MPO VUMPS
This function will largely use the previos defined functions
Ref: Hao-Ti Hung's thesis p.26
##############################################################
'''
def vumps_mpo(W,A,eta = 1e-8):
    print('>'*100)
    print('VUMPS for MPO begin!')
    def map_Hac(Ac):
        Ac = Ac.reshape(D,d,D)
        # e_eye = energy* np.eye(d ** 2, d ** 2).reshape(d, d, d, d)
        Ac_new = ncon([L_W,Ac,W,R_W],
                      [[-1,3,1],[1,5,2],[3,4,5,-2],[-3,4,2]])
        return Ac_new.reshape(-1)
    def map_Hc(C):
        C= C.reshape(D,D)
        C_new = ncon([L_W,C,R_W],
                     [[-1,3,1],[1,2],[-2,3,2]])
        return C_new.reshape(-1)
    D, d, _ = A.shape
    lam, gamma = A_to_lam_gamma(A)
    lam, gamma = lam_gamma_to_canonical(lam, gamma)
    A_L, A_R = canonical_to_Al_Ar(lam, gamma)
    C = lam
    Ac = ncon([A_L, C],
              [[-1, -2, 1], [1, -3]])
    delta = eta * 1000
    e_memory = -1
    e = 0
    count = 0

    while (delta > eta and abs(e - e_memory) > eta / 10) or count <15:
        L_W, R_W, energy = get_Lh_Rh_mpo(A_L,A_R,C,W)
        E_Ac, Ac = eigs(LinearOperator((D ** 2 * d, D ** 2 * d), matvec=map_Hac), k=1, which='SR',
                        v0=Ac.reshape(-1), tol=delta / 10)
        Ac = Ac.reshape(D, d, D)
        E_C, C = eigs(LinearOperator((D ** 2, D ** 2), matvec=map_Hc), k=1, which='SR',
                      v0=C.reshape(-1), tol=delta / 10)
        C = C.reshape(D, D)
        e_memory = e
        e = energy
        A_L, A_R = min_Ac_C(Ac, C)
        Al_C = ncon([A_L, C],
                    [[-1, -2, 1], [1, -3]])
        delta = linalg.norm(Ac - Al_C)
        if count % 5 == 0:
            print(50 * '-' + 'steps', count, 50 * '-')
            print('energy = ', e)
            print('delta = ', delta)
            print('Eac = ', E_Ac)
            print('Ec = ', E_C)
            print('Eac-Ec = ', E_Ac-E_C)
            print('Eac/Ec = ', E_Ac/E_C)
        count += 1
    print(50 * '-' + ' final ' + 50 * '-')
    print('delta = ', delta)
    print('energy = ', e)
    # test_energy = ncon([L_W,Ac,W,np.conj(Ac),R_W],
    #                    [[3,2,1],[1,7,4],[2,5,7,8],[3,8,6],[6,5,4]])
    # print('test_energy = ', test_energy)
    # exit()
    return e, Ac, C, A_L, A_R, L_W, R_W

'''
##############################################################
vumps_fixed_points
##############################################################
'''

def A_W_to_Tw(A_L, W):
    '''Get T_Wl or T_Wr
    See eqn(250) in arXiv:1810.07006v3'''
    T_W = ncon([A_L, W, np.conj(A_L)],
                [[-6,1,-3], [-5,-2,1,2], [-4,2,-1]])
    return T_W

def fixed_boundary(A_L,W,eta = 1e-8):
    d_w, _, _, _ = W.shape
    D, d, _ = A_L.shape
    T_W = A_W_to_Tw(A_L,W)
    T_W = T_W.reshape(D**2*d_w,D**2*d_w)
    lam, Lw = eigs(T_W, k=1, which='LM',tol=eta)
    Lw = Lw.reshape(D,d_w,D)
    return lam, Lw

def overlap_fixed_boundary(Lw,Rw,C):
    overlap = ncon([Lw,C,Rw,np.conj(C)],
                   [[4,3,1], [1,2], [5,3,2], [4,5]])
    return overlap

def vumps_fixed_points(W,A,eta=1e-8):
    def map_Hac(Ac):
        Ac = Ac.reshape(D,d,D)
        Ac_new = ncon([Lw,Ac,W,Rw],
                      [[-1,3,1],[1,5,2],[3,4,5,-2],[-3,4,2]])/lam1
        return Ac_new.reshape(-1)
    def map_Hc(C):
        C= C.reshape(D,D)
        C_new = ncon([Lw,C,Rw],
                     [[-1,3,1],[1,2],[-2,3,2]])
        return C_new.reshape(-1)
    D, d, _ = A.shape
    lam, gamma = A_to_lam_gamma(A)
    lam, gamma = lam_gamma_to_canonical(lam, gamma)
    A_L, A_R = canonical_to_Al_Ar(lam, gamma)
    C = lam
    Ac = ncon([A_L, C],
              [[-1, -2, 1], [1, -3]])
    delta = eta * 1000
    count = 0

    while (delta > eta) or count <15:
        lam1, Lw = fixed_boundary(A_L,W,delta/10)
        W_r = W.transpose([1, 0, 2, 3])
        lam2, Rw = fixed_boundary(A_R, W_r, delta/10)

        norm = overlap_fixed_boundary(Lw,Rw,C)
        Lw = Lw/norm
        lam_Ac, Ac = eigs(LinearOperator((D ** 2 * d, D ** 2 * d), matvec=map_Hac), k=1, which='LM',
                        v0=Ac.reshape(-1), tol=delta / 10)
        Ac = Ac.reshape(D, d, D)
        lam_C, C = eigs(LinearOperator((D ** 2, D ** 2), matvec=map_Hc), k=1, which='LM',
                      v0=C.reshape(-1), tol=delta / 10)
        C = C.reshape(D, D)
        # print('lam_Ac = ', lam_Ac)
        # print('lam_C = ', lam_C)
        A_L, A_R = min_Ac_C(Ac, C)
        Al_C = ncon([A_L, C],
                    [[-1, -2, 1], [1, -3]])
        delta = linalg.norm(Ac - Al_C)

        if count % 10 == 0:
            print(50 * '-' + 'steps', count, 50 * '-')
            print('delta = ', delta)
            print('lam1 = ', lam1)
            print('lam2 = ', lam2)
            print('norm = ', norm)
        count += 1
        if count > 200 and delta > 1e-3:
            A = np.random.rand(D,d,D)
            lam, gamma = A_to_lam_gamma(A)
            lam, gamma = lam_gamma_to_canonical(lam, gamma)
            A_L, A_R = canonical_to_Al_Ar(lam, gamma)
            C = lam
            Ac = ncon([A_L, C],
                      [[-1, -2, 1], [1, -3]])
            delta = eta * 1000
            count = 0
    print('delta = ', delta)
    print('converge!')
    return lam1, Ac, C, A_L, A_R, Lw, Rw
'''
########################################################################################################################
Excitation Part
########################################################################################################################
'''
def get_T_RLw_or_T_LRw(A_R, W, A_L):
    '''Thie is ued in [quasiparticle_correct], which should be the correct transfer
    matrix to be used'''
    T_RL = ncon([A_R,W,np.conj(A_L)],
                [[-3,2,-6],[-5,-2,2,1], [-4,1,-1]])
    return T_RL

def get_T_RL_or_T_LR(A_R,A_L):
    T_RL = ncon([A_R, np.conj(A_L)],
                [[-2,1,-4],[-3,1,-1]])
    return T_RL

def combine_LBWA_L(L_W, B, W, A_L):
    LBWA_L = ncon([L_W, B, W, np.conj(A_L)],
               [[1,2,3],[3,5,-3],[2,-2,5,4],[1,4,-1]])
    return LBWA_L

def combine_RBWA_R(R_W, B, W, A_R):
    RBWA_R = ncon([R_W,B,W,np.conj(A_R)],
                  [[1,2,3],[-3,5,3],[-2,2,5,4],[1,4,-1]])
    return RBWA_R

def quasiparticle_mpo(W, p, A_L, A_R, L_W, R_W, num_of_excite=1, system ='1D', pinv = 'scipy'):
    '''
    Corrected version of quasiparticle.
    :param W: MPO
    :param p: momentum
    :param A_L: Used to get mpo transfer matrix and LBWA_L
    :param A_R: Used to get mpo transfer matrix and RBWA_R
    :param L_W: Left fixed point of MPO, which is obtained from vumps_mpo.
    :param R_W: Right fixed point of MPO, which is obtained from vumps_mpo.
    :return: omega and X
    '''
    T_RL = get_T_RLw_or_T_LRw(A_R, W, A_L)
    D,dw = T_RL.shape[0], T_RL.shape[1]

    # test = inv_T_RL@(mat_eye-mat_T_RL)
    # print(np.around(test))
    # exit()
    W_r = W.transpose([1, 0, 2, 3])
    T_LR = get_T_RLw_or_T_LRw(A_L, W_r, A_R)

    # T_RL *= np.exp(-1j * p)
    # T_LR *= np.exp(1j * p)
    if pinv == 'scipy':
        mat_T_RL = T_RL.reshape(D ** 2 * dw, -1) * np.exp(-1j * p)
        mat_eye = np.eye(D ** 2 * dw, D ** 2 * dw)
        # print(mat_T_RL.shape)
        inv_T_RL = linalg.pinv(mat_eye - mat_T_RL).reshape([D, dw, D] * 2)
        mat_T_LR = T_LR.reshape(D ** 2 * dw, -1) * np.exp(1j * p)
        # print(mat_T_RL.shape)
        inv_T_LR = linalg.pinv(mat_eye - mat_T_LR).reshape([D, dw, D] * 2)
        print('hello')
    else:
        r_L, l_L = pinv_manual.Tw_to_rl(T_RL)
        l_R, r_R = pinv_manual.Tw_to_rl(T_LR)
        T_RL *= np.exp(-1j * p)
        T_LR *= np.exp(1j * p)
    D, d, _ = A_L.shape
    A_tmp = A_L.reshape(D * d, D).T
    V_L = linalg.null_space(A_tmp)
    V_L = V_L.reshape(D, d, D*(d-1))
    def map_effective_H(X):
        X = X.reshape(D*(d-1),D)
        B = ncon([V_L,X],
                 [[-1,-2,1],[1,-3]])
        LBWA_L = combine_LBWA_L(L_W, B, W, A_L)
        RBWA_R = combine_RBWA_R(R_W, B, W, A_R)
        if pinv == 'scipy':
            L_B = ncon([inv_T_RL, LBWA_L],
                       [[-1,-2,-3,1,2,3], [1,2,3]])
            R_B = ncon([inv_T_LR, RBWA_R],
                       [[-1,-2,-3,1,2,3], [1,2,3]])
        else:
            L_B = pinv_manual.quasi_sum_right_left_mpo(T_RL, r_L, l_L, LBWA_L)
            R_B = pinv_manual.quasi_sum_right_left_mpo(T_LR, l_R, r_R, RBWA_R)
        term1 = np.exp(-1j*p)*ncon([L_B,A_R,W,R_W],
                                    [[-1,1,2],[4,5,2],[1,3,5,-2],[-3,3,4]])
        term2 = np.exp(1j*p)*ncon([L_W,A_L,W,R_B],
                                  [[-1,1,2],[2,5,4],[1,3,5,-2],[-3,3,4]])
        term3 = ncon([L_W,B,W,R_W],
                     [[-1,1,2],[2,5,4],[1,3,5,-2],[-3,3,4]])
        Teff_B = term1+term2+term3
        Teff_X = ncon([Teff_B, np.conj(V_L)],
                      [[1,2,-2],[1,2,-1]])
        return Teff_X.reshape(-1)
    # omega, X = eigs(LinearOperator((D ** 2*(d-1), D ** 2*(d-1)), matvec=map_effective_H), k=10, which='SR', tol=1e-6)
    if system == '1D':
        omega, X = eigsh(LinearOperator((D ** 2*(d-1), D ** 2*(d-1)), matvec=map_effective_H), k=num_of_excite, which='SA', tol=1e-6)
    elif system == 'AKLT':
        # omega, X = eigs(LinearOperator((D ** 2 * (d - 1), D ** 2 * (d - 1)), matvec=map_effective_H), k=num_of_excite, which='LM',
        #                 tol=1e-6)
        omega1, X = eigsh(LinearOperator((D ** 2 * (d - 1), D ** 2 * (d - 1)), matvec=map_effective_H), k=num_of_excite,
                         which='LA', tol=1e-6)
        # print('omega1 = ', omega1)
        omega2, X = eigsh(LinearOperator((D ** 2 * (d - 1), D ** 2 * (d - 1)), matvec=map_effective_H), k=num_of_excite,
                          which='SA', tol=1e-6)
        # print('omega2 = ', omega2)
        omega = np.hstack((omega1, omega2))
    elif system == '2D':
        omega, X = eigs(LinearOperator((D ** 2 * (d - 1), D ** 2 * (d - 1)), matvec=map_effective_H), k=num_of_excite,
                        which='LM', tol=1e-6)
    X = X[:,0].reshape(D*(d-1),D)
    B = ncon([V_L, X],
             [[-1, -2, 1], [1, -3]])
    # LBWA_L = combine_LBWA_L(L_W, B, W, A_L)
    # test = ncon([LBWA_L, r_L],
    #             [[1,2,3], [1,2,3]])
    # print('testing LBWA_L:',test)
    # RBWA_R = combine_RBWA_R(R_W, B, W, A_R)
    # test = ncon([RBWA_R, l_R],
    #             [[1, 2, 3], [1, 2, 3]])
    # print('testing RBWA_R:',test)
    return omega, X

def quasiparticle_2sites(h2sites, p, A_L, A_R, L_h, R_h, num_of_excite=5):
    T_RL = get_T_RL_or_T_LR(A_R,A_L)
    T_LR = get_T_RL_or_T_LR(A_L,A_R)
    r_L, l_L = pinv_manual.T_to_rl(T_RL)
    l_R, r_R = pinv_manual.T_to_rl(T_LR)
    T_RL *= np.exp(-1j * p)
    T_LR *= np.exp(1j * p)
    D, d, _ = A_L.shape
    A_tmp = A_L.reshape(D * d, D).T
    V_L = linalg.null_space(A_tmp)
    V_L = V_L.reshape(D, d, D*(d-1))
    Heff_B = [None] * 14
    L1x = [None] * 4
    R1x = [None] * 4
    def map_effective_H(X):
        X = X.reshape(D*(d-1),D)
        B = ncon([V_L,X],
                 [[-1,-2,1],[1,-3]])
        L_Bx = ncon([B, np.conj(A_L)],
                    [[1,2,-2],[1,2,-1]])
        R_Bx = ncon([B,np.conj(A_R)],
                    [[-2,2,1],[1,2,-1]])
        L_B = pinv_manual.quasi_sum_right_left_2sites(T_RL,r_L,l_L, L_Bx)
        # print(linalg.norm(L_B))
        # print('L_B = ', L_B)
        # print(R_Bx)
        # exit()
        R_B = pinv_manual.quasi_sum_right_left_2sites(T_LR,l_R,r_R,R_Bx)
        # print('R_Bx = ', R_Bx)
        # exit()

        L1x[0] = ncon([B,L_h,np.conj(A_L)],
                       [[2,3,-2],[1,2],[1,3,-1]])
        L1x[1] = ncon([A_L, B, h2sites, np.conj(A_L), np.conj(A_L)],
                      [[1,3,2],[2,4,-2],[3,4,5,6],[1,5,7],[7,6,-1]])
        L1x[2] = np.exp(-1j*p)*ncon([B, A_R, h2sites, np.conj(A_L), np.conj(A_L)],
                                    [[1,3,2],[-2,4,2],[3,4,5,6],[1,5,7],[7,6,-1]])
        L1x[3] = np.exp(-2j*p)*ncon([L_B, A_R, A_R, h2sites, np.conj(A_L), np.conj(A_L)],
                                    [[1,2],[3,4,2],[-2,5,3],[4,5,6,7],[1,6,8],[8,7,-1]])
        L1x_sum = sum(L1x)
        L1 = pinv_manual.quasi_sum_right_left_2sites(T_RL, r_L, l_L, L1x_sum)

        R1x[0] = ncon([B,R_h,np.conj(A_R)],
                       [[-2,3,2],[1,2],[1,3,-1]])
        R1x[1] = ncon([B, A_R, h2sites, np.conj(A_R), np.conj(A_R)],
                      [[-2,2,1],[6,3,1],[2,3,4,5],[7,4,-1],[6,5,7]])
        R1x[2] = np.exp(1j*p)*ncon([A_L, B, h2sites, np.conj(A_R), np.conj(A_R)],
                                   [[-2,2,1],[1,3,6],[2,3,4,5],[7,4,-1],[6,5,7]])
        R1x[3] = np.exp(2j*p)*ncon([A_L, A_L, h2sites, np.conj(A_R), np.conj(A_R), R_B],
                                   [[-2,2,1],[1,3,6],[2,3,4,5],[8,4,-1],[7,5,8],[7,6]])
        R1x_sum = sum(R1x)
        R1 = pinv_manual.quasi_sum_right_left_2sites(T_LR,l_R,r_R,R1x_sum)
        # Heff_B = [None]*14
        Heff_B[0] = ncon([B, A_R, h2sites, np.conj(A_R)],
                         [[-1,3,1],[2,4,1],[3,4,-2,5],[2,5,-3]])
        Heff_B[1] = np.exp(-1j*p)*ncon([B, A_R, h2sites, np.conj(A_L)],
                                       [[1,3,2],[-3,4,2],[3,4,5,-2],[1,5,-1]])
        Heff_B[2] = np.exp(1j*p)*ncon([A_L, B, h2sites, np.conj(A_R)],
                                      [[-1,3,1],[1,4,2],[3,4,-2,5],[2,5,-3]])
        Heff_B[3] = ncon([A_L, B, h2sites, np.conj(A_L)],
                         [[1,3,2],[2,4,-3],[3,4,5,-2],[1,5,-1]])
        Heff_B[4] = ncon([B,R_h],
                         [[-1,-2,1],[-3,1]])
        Heff_B[5] = ncon([L_h,B],
                         [[-1,1],[1,-2,-3]])
        Heff_B[6] = np.exp(-1j*p)*ncon([L1,A_R],
                                       [[-1,1],[-3,-2,1]])
        Heff_B[7] = np.exp(1j*p)*ncon([A_L,R1],
                                      [[-1,-2,1],[-3,1]])
        Heff_B[8] = np.exp(-1j*p)*ncon([L_B,A_R,R_h],
                                       [[-1,1],[2,-2,1],[-3,2]])
        Heff_B[9] = np.exp(1j*p)*ncon([L_h,A_L,R_B],
                                      [[-1,1],[1,-2,2],[-3,2]])
        Heff_B[10] = np.exp(-1j*p)*ncon([L_B, A_R, A_R, h2sites, np.conj(A_R)],
                                        [[-1,1],[2,4,1],[3,5,2],[4,5,-2,6],[3,6,-3]])
        Heff_B[11] = np.exp(-2j*p)*ncon([L_B, A_R, A_R, h2sites, np.conj(A_L)],
                                        [[6,1],[2,3,1],[-3,4,2],[3,4,5,-2],[6,5,-1]])
        Heff_B[12] = np.exp(1j*p)*ncon([A_L, A_L, h2sites, np.conj(A_L), R_B],
                                       [[1,4,2],[2,5,3],[4,5,6,-2],[1,6,-1],[-3,3]])
        Heff_B[13] = np.exp(2j*p)*ncon([A_L, A_L, h2sites, np.conj(A_R), R_B],
                                       [[-1,3,1],[1,4,2],[3,4,-2,5],[6,5,-3],[6,2]])
        Heff_B_final = sum(Heff_B)
        Heff_X = ncon([Heff_B_final, np.conj(V_L)],
                      [[1,2,-2],[1,2,-1]])
        return Heff_X.reshape(-1)
    # omega, X = eigs(LinearOperator((D ** 2*(d-1), D ** 2*(d-1)), matvec=map_effective_H), k=10, which='SR', tol=1e-6)
    omega, X = eigsh(LinearOperator((D ** 2*(d-1), D ** 2*(d-1)), matvec=map_effective_H), k=num_of_excite, which='SA', tol=1e-8)
    X = X[:,0]
    _ = map_effective_H(X)
    X = X.reshape(D * (d - 1), D)

    L1x_test = sum(L1x)


    R1x_test = sum(R1x)

    H = [None]*14
    for i in range(len(H)):
        Heff_X = ncon([Heff_B[i], np.conj(V_L)],
                      [[1, 2, -2], [1, 2, -1]])
        H[i] = ncon([Heff_X, np.conj(X)],
                    [[1,2],[1,2]])
        # if abs(H[i]) > 1e-8:
            # print('H_%d = '%i, H[i])
        # else: print('H_%d = '%i, 0)
    print('sum(H) = ', sum(H))
    return omega

def domain_sum_right_left(T_R2L1,x):
    '''For domain part, we use regular inverse instead of pseudo inverse'''
    D, d_w, _ = x.shape
    def map_inv_L(y):
        y = y.reshape(D,d_w,D)
        term1 = y
        term2 = ncon([T_R2L1, y],
                     [[-1,-2,-3,1,2,3],[1,2,3]])
        y_out = term1 - term2
        return y_out.reshape(-1)
    y, info = bicgstab(LinearOperator((D ** 2 * d_w, D ** 2 * d_w), matvec=map_inv_L), x.reshape(-1),
                       x0=x.reshape(-1))
    if info != 0:
        print('bicgstab did not converge!')
        exit()
    y = y.reshape(D,d_w,D)
    return y

def quasiparticle_domain(W, p, A_L1, A_R2, L_W, R_W, num_of_excite=1):
    D, d, _ = A_L1.shape
    d_w, _, _, _ = W.shape
    A_tmp = A_L1.reshape(D * d, D).T
    V_L = linalg.null_space(A_tmp)
    V_L = V_L.reshape(D, d, D * (d - 1))
    T_R2L1 = get_T_RLw_or_T_LRw(A_R2, W, A_L1)
    lval, l = eigs(T_R2L1.reshape(D**2*d_w,D**2*d_w),k=1, which='LM')
    A_R2*= np.conj(lval)/linalg.norm(lval)
    T_R2L1 = get_T_RLw_or_T_LRw(A_R2, W, A_L1)
    T_R2L1 *= np.exp(-1j*p)
    W_r = W.transpose([1, 0, 2, 3])
    T_L1R2 = get_T_RLw_or_T_LRw(A_L1, W_r, A_R2)
    T_L1R2 *= np.exp(1j*p)
    # print('solving eigsh')
    def map_effective_H(X):
        # print('doing map_H')
        X = X.reshape(D*(d-1),D)
        B = ncon([V_L,X],
                 [[-1,-2,1],[1,-3]])
        LBWA_L1 = combine_LBWA_L(L_W, B, W, A_L1)
        RBWA_R2 = combine_RBWA_R(R_W, B, W, A_R2)
        L_B = domain_sum_right_left(T_R2L1, LBWA_L1)
        R_B = domain_sum_right_left(T_L1R2, RBWA_R2)
        term1 = np.exp(-1j*p)*ncon([L_B,A_R2,W,R_W],
                                    [[-1,1,2],[4,5,2],[1,3,5,-2],[-3,3,4]])
        term2 = np.exp(1j*p)*ncon([L_W, A_L1, W, R_B],
                                  [[-1,1,2],[2,5,4],[1,3,5,-2],[-3,3,4]])
        term3 = ncon([L_W,B,W,R_W],
                     [[-1,1,2],[2,5,4],[1,3,5,-2],[-3,3,4]])
        Teff_B = term1+term2+term3
        Teff_X = ncon([Teff_B, np.conj(V_L)],
                      [[1,2,-2],[1,2,-1]])
        return Teff_X.reshape(-1)
    # omega, X = eigsh(LinearOperator((D ** 2 * (d - 1), D ** 2 * (d - 1)), matvec=map_effective_H), k=num_of_excite, which='SA',
    #                  tol=1e-8)
    # omega, X = eigs(LinearOperator((D ** 2 * (d - 1), D ** 2 * (d - 1)), matvec=map_effective_H), k=10, which='SR',
    #                 tol=1e-6)
    omega, X = eigs(LinearOperator((D ** 2 * (d - 1), D ** 2 * (d - 1)), matvec=map_effective_H), k=num_of_excite,
                    which='LM', tol=1e-6)
    return omega
'''
########################################################################################################################
Main Program
########################################################################################################################
'''

if __name__ == '__main__':
    D = 10;
    d = 2
    A = np.random.rand(D, d, D)
    lam, gamma = A_to_lam_gamma(A)
    lam, gamma = lam_gamma_to_canonical(lam, gamma)
    A_L, A_R = canonical_to_Al_Ar(lam, gamma)
    C = lam
    Ac = ncon([A_L, C],
              [[-1, -2, 1], [1, -3]])
    A_L2, A_R2 = min_Ac_C(Ac, C)
    del_AL = linalg.norm(A_L - A_L2) / linalg.norm(A_L)
    del_AR = linalg.norm(A_R - A_R2) / linalg.norm(A_R)
    print(del_AL, del_AR)
    exit()
    sX, sY, sZ, sI = constants.get_spin_operators(d)
    model = 'TFIM'
    hz_field = 0.9
    Model = constants.Model(model, d, hz_field)
    hloc, W, Exact = Model.get_h_W_E()
    print('Exact = ', Exact)

    # filename = 'omega_p_hz09test.txt'
    print('We are solving ' + model + ' model!')
    aklt = constants.get_AKLT()
    dim = aklt.shape[1]
    W = ncon([aklt, np.conj(aklt)],
             [[1, -1, -3, -5, -7], [1, -2, -4, -6, -8]])
    d = dim**2
    W = W.reshape(d, d, d, d)
    W = W/1.30574397
    '''rvb = constants.get_RVB()
    dim = rvb.shape[-1]
    d = dim**2
    W = ncon([rvb, np.conj(rvb)],
             [[1,2,3,-1, -3, -5, -7], [1,2,3, -2, -4, -6, -8]])
    W = W.reshape(d, d, d, d)
    print(rvb.shape)'''
    print(W.shape)
    # exit()
    print('D = ', D)

    # d_w = 3
    # W = np.random.rand(d_w, d_w, d, d)
    lam1, Ac, C, A_L, A_R, L_W, R_W = vumps_fixed_points(W, A, eta=1e-5)
    print(lam1)
    # filename = 'akltD15.txt'
    # filename = 'rvbD8.txt'
    num_of_p = 10
    num_of_excite = 5
    '''p = 0
    omega, _ = quasiparticle_mpo(W, p, A_L, A_R, L_W, R_W, num_of_excite=5, system_dim='2D')
    print(omega)
    print(-np.log(sorted(abs(omega / lam1))))
    omega, _ = quasiparticle_mpo(W, p, A_L, A_R, L_W, R_W, num_of_excite=5, system_dim='2D')
    print(omega)
    print(-np.log(sorted(abs(omega / lam1))))
    omega, _ = quasiparticle_mpo(W, p, A_L, A_R, L_W, R_W, num_of_excite=5, system_dim='2D')
    print(omega)
    print(-np.log(sorted(abs(omega / lam1))))
    exit()
    with open(filename, 'w') as f:
        f.write('# omega \t p \n')
        f.write('# rvb \n')
    for p in np.linspace(np.pi*0.0, np.pi/2, num_of_p):
        print('p = ', p)
        omega, _ = quasiparticle_mpo(W, p, A_L, A_R, L_W, R_W, num_of_excite=num_of_excite, system_dim='2D')
        min_ln = list(-np.log(abs(omega / lam1)))
        min_ln.sort()
        f = open(filename, 'a')
        message = ('{:.3f}, ' + '{:.5f}, '*(num_of_excite-1)+ '{:.5f}').format(p, *min_ln)
        print(message)
        f.write(message)
        f.write('\n')
        f.close()
    exit()
    '''

    with open(filename, 'w') as f:
        f.write('# omega \t p \n')
        f.write('# aklt \n')
    for p in np.linspace(np.pi*0.0, np.pi, num_of_p):
        print('p = ', p)
        omega, _ = quasiparticle_mpo(W, p, A_L, A_R, L_W, R_W, num_of_excite=num_of_excite, system='2D')
        omega = omega.real
        omega_kx_0 = list(omega[omega>0])
        omega_kx_pi = list(omega[omega<0])
        print('omega_kx_0 = ', omega_kx_0)
        print('omega_kx_pi = ', omega_kx_pi)
        lam1 = abs(lam1)
        min_ln_0 = list(-np.log(abs(omega_kx_0 / lam1)))
        min_ln_0.sort()
        print('min_ln_0 = ', min_ln_0)
        min_ln_pi = list(-np.log(abs(omega_kx_pi / lam1)))
        min_ln_pi.sort()
        print('min_ln_pi = ', min_ln_pi)



        f = open(filename, 'a')
        message = ('{:.3f}, ' + '{:.5f}, '*(len(min_ln_0)-1)+ '{:.5f}').format(p, *min_ln_0)
        print(message)
        f.write(message)
        f.write('\n')
        message = ('{:.3f}, ' + '{:.5f}, ' * (len(min_ln_pi) - 1) + '{:.5f}').format(p, *min_ln_pi)
        print(message)
        f.write(message)
        f.write('\n')
        f.close()
    exit()
    omega, _ = quasiparticle_mpo(W, p, A_L, A_R, L_W, R_W, num_of_excite=5, system='2D')
    print(omega)
    print(-np.log(abs(omega/lam1)))
    omega, _ = quasiparticle_mpo(W, p, A_L, A_R, L_W, R_W, num_of_excite=5, system='2D')
    print(omega)
    omega, _ = quasiparticle_mpo(W, p, A_L, A_R, L_W, R_W, num_of_excite=5, system='2D')
    print(omega)

    exit()



    e_cal, A_L, A_R, Ac,C,L_h, R_h = vumps_2sites(hloc, A, eta=1e-6)
    e_eye = e_cal * np.eye(d ** 2, d ** 2).reshape(d, d, d, d)
    h_tilda = hloc - e_eye

    exit()
    p_xaxis_ = []
    omega_triv = []
    # omega_nontriv = []
    num_of_p = 5
    num_of_excite = 5
    with open(filename, 'w') as f:
        f.write('# omega \t p \n')
        f.write('# 2sites \n')
    for p in np.linspace(np.pi*0.0, np.pi*1.0, num_of_p):
        print('p = ', p)
        omega = quasiparticle_2sites(h_tilda, p, A_L, A_R, L_h, R_h, num_of_excite)
        omega += e_cal.real
        omega_triv.append(omega.real)
        f = open(filename, 'a')
        message = ('{:.3f}, ' + '{:.5f}, '*4+ '{:.5f}').format(p, *omega.real)
        print(message)
        f.write(message)
        f.write('\n')
        f.close()
        # print('omega[0] = ', omega[0].real)
        # omega = quasiparticle_2sites(hloc, p, A_L, A_R, L_h, R_h, num_of_excite)
        # print('omega[0] = ', omega[0].real - e_cal.real)
        # omega_triv.append(omega.real - e_cal.real)
        # omega_yaxis.append(omega.real)
        # print('omega-e_cal (trivial)= ', omega - e_cal)
        p_xaxis_.append([p] * num_of_excite)

    e_cal, Ac, C, A_L, A_R, L_W, R_W = vumps_mpo(W,A, eta=1e-8)
    A_L1 = A_L
    A_R2 = ncon([A_R, sZ],
                [[-1, 1, -3], [1, -2]])
    # p = 0.0
    # omega, X = quasiparticle_correct(W, p, A_L, A_R, L_W, R_W)
    # print(omega)
    p_xaxis_ = []
    omega_triv = []
    omega_nontriv = []
    num_of_p = 5
    num_of_excite = 5
    f = open(filename, 'a')
    f.write('# mpo \n')
    f.close()
    for p in np.linspace(0, np.pi*10/10, num_of_p):
        print('p = ', p)
        omega, X = quasiparticle_mpo(W, p, A_L, A_R, L_W, R_W, num_of_excite)
        f = open(filename, 'a')
        omega -= e_cal.real
        message = ('{:.3f}, ' + '{:.5f}, '*4+ '{:.5f}').format(p, *omega.real)
        print(message)
        f.write(message)
        f.write('\n')
        f.close()
        # exit()
        omega_triv.append(omega.real - e_cal.real)
        # omega_yaxis.append(omega.real)
        print('omega-e_cal (trivial)= ', omega-e_cal)
        p_xaxis_.append([p] * num_of_excite)
        # omega = quasiparticle_domain(W,p, A_L1, A_R2, L_W, R_W, num_of_excite)
        # omega_nontriv.append(omega.real - e_cal.real)
        # print('omega-e_cal (non-trivial)= ', omega - e_cal)
        # print(omega)
    # elem_ex = lambda k: np.sqrt(1 + hz_field ** 2 - 2 * hz_field * np.cos(k))
    '''omega_triv = np.array(omega_triv).ravel()
    p_xaxis_ = np.array(p_xaxis_).ravel()
    plt.plot(p_xaxis_, omega_triv, 'bo', label ='trivial')
    omega_nontriv = np.array(omega_nontriv).ravel()
    p_xaxis_nontriv = np.array(p_xaxis_).ravel()
    plt.plot(p_xaxis_nontriv, omega_nontriv, 'ro', label='non-trivial')
    p = np.linspace(0, np.pi, num=100)
    plt.plot(p, elem_ex(p), 'c-', label='exact')
    plt.title('TFIM Excitation:'+' hz = '+str(hz_field))
    # plt.title('XXZ Excitation:' + ' delta = ' + str(delta))
    plt.xlabel('Momentum p')
    plt.ylabel('dE')
    plt.grid()
    plt.legend()
    plt.show()'''
    exit()

    # print(L_W1)
    lam, gamma = A_to_lam_gamma(A)
    lam, gamma = lam_gamma_to_canonical(lam, gamma)
    A_L, A_R = canonical_to_Al_Ar(lam,gamma)
    C = lam
    Ac = ncon([A_L,C],
              [[-1,-2,1], [1,-3]])

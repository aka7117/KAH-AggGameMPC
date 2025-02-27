import numpy as np
import scipy.io
from scipy.optimize import linprog, minimize
import matplotlib.pyplot as plt
from tqdm import tqdm

class LoadOptimization:
    
    def __init__(self, load_file, cars_file):
        
        print("Loading data...")
        self.load_data = scipy.io.loadmat(load_file)
        self.car_data = scipy.io.loadmat(cars_file)

        # Extract the necessary data from .mat files based on the provided MATLAB code
        self.load = self.load_data['BL'].flatten()
        self.cars = self.car_data['Cars'][0, 0]  # Adjusting to match MATLAB struct indexing

        # Extract fields from the cars data
        self.cars_fields = {
            'Xub': self.cars['Xub'][0].flatten(),
            'Xlb': self.cars['Xlb'][0].flatten(),
            'BatteryCapacity': self.cars['BatteryCapacity'][0].flatten(),
            'Tin': self.cars['Tin'][0].flatten(),
            'ISOC': self.cars['ISOC'][0].flatten(),
            'DSOC': self.cars['DSOC'][0].flatten(),
            'Tout': self.cars['Tout'][0].flatten(),
            'Tav': self.cars['Tav'][0].flatten(),
        }
        print("Data loaded successfully.")

    def cons_find(self, Tin, Tout, T, ISOC, DSOC, Bat, Sigma, Lnoti, Xub, Xlb, SOCmin, SOCmax):
        
        ### All Checked on 7/29/2024 ###
        E0 = ISOC * Bat
        Emin = SOCmin * Bat
        Emax = SOCmax * Bat
        Ed = (Emin - E0) / Sigma
        Eu = (Emax - E0) / Sigma
        En = (DSOC - ISOC) * Bat / Sigma

        
        # 1. Constraints on y (or overall load)
        lb = np.tile([0, 0, 0], T)
        ub = np.tile([6000, 2000, 4000], T)

        # 2. Constraints on x(t) = sum(y(t)) - Lnoti(t)
        A11 = np.zeros((T, 3 * T))
        
        for i in range(T):
        
            A11[i, 3 * i:3 * (i + 1)] = 1
        
        A12 = -A11
        
        A1 = np.vstack((A11, A12))

        b11 = (Xub * np.ones(T)) + Lnoti
        b12 = (-1 * Xlb * np.ones(T)) - Lnoti
        b1 = np.hstack((b11, b12))

        # 3. Constraints over SOC bounds:  MinEnergy <= InitialEnergy + AllEnergyReceivedUpToNow <= MaxEnergy
        A21 = np.ones((T, 3 * T))

        for i in range(T - 1):
           
            A21[i, 3 * (i + 1):] = 0
       
        A22 = -A21
        
        A2 = np.vstack((A21, A22))

        SLnoti = np.cumsum(Lnoti)

        b21 = (Eu * np.ones(T)) + SLnoti
        b22 = (-1 * Ed * np.ones(T)) - SLnoti
        
        b2 = np.hstack((b21, b22))

        A = np.vstack((A1, A2))
        b = np.hstack((b1, b2))

        
        # 4. Desired SoC Constraint
        Aeq1 = np.ones(3 * T)
        beq1 = En + SLnoti[-1]


        # 5. Unavailable time constraint
        Aeq21 = np.zeros((Tin - 1, 3 * T))
        
        for i in range(Tin - 1):
            
            Aeq21[i, 3 * i:3 * (i + 1)] = 1
        
        beq21 = Lnoti[:Tin - 1]

        Tnot = T - Tout + 1
        
        Aeq22 = np.zeros((Tnot, 3 * T))
        
        for i in range(Tout, T + 1):
        
            Aeq22[i - Tout, 3 * (i - 1):3 * i] = 1
        
        beq22 = Lnoti[Tout - 1:T]

        Aeq2 = np.vstack((Aeq21, Aeq22))
        beq2 = np.hstack((beq21, beq22))

        Aeq = np.vstack((Aeq1, Aeq2))
        beq = np.hstack((beq1, beq2))

        return lb, ub, A, b, Aeq, beq

    from scipy.optimize import minimize

    def optimizer(self, Lnoti, Bat, ISOC, DSOC, k, T, sigma, Tin, Tout, Xub, xlb, a1, a2, delta):
            
        SOCmin = 0.1
        SOCmax = 1
        Prc = np.array([1.1, 1.15, 1.2]) * np.array([6.5, 9.4, 13.2])
        Pr = np.tile(Prc, T)

        lb, ub, A, b, Aeq, beq = self.cons_find(Tin, Tout, T, ISOC, DSOC, Bat, sigma, Lnoti, Xub, xlb, SOCmin, SOCmax)

        success = True

        Q = np.zeros((3 * T, 3 * T))
        
        for i in range(T):
            Q[3 * i:3 * (i + 1), 3 * i:3 * (i + 1)] = np.ones((3, 3))
        
        Q = 2 * k * delta * Q

        f1 = Pr
        f = a1 * f1

        # Finding FF for normalizing factor
        res1 = linprog(f1, A_ub=A, b_ub=b, A_eq=Aeq, b_eq=beq, bounds=list(zip(lb, ub)))
    
        if res1.success:
            x1 = res1.x
            FF = res1.fun
            print(f"Linprog success: {res1.message}")
        else:
            success = False
            x1 = np.zeros(3 * T)
            FF = 0
            print(f"Linprog failed: {res1.message}")

        # Finding FFF for normalizing factor
        Q2 = a2 * Q
        f2 = np.zeros(3 * T)

        if k != 0 and success:

            # Set up the constraints for minimize function
            ineq_constraints = {'type': 'ineq', 'fun': lambda x: b - np.dot(A, x)}
            eq_constraints = {'type': 'eq', 'fun': lambda x: np.dot(Aeq, x) - beq}

            res2 = minimize(lambda x: 0.5 * np.dot(x.T, np.dot(Q2, x)), x1, bounds=list(zip(lb, ub)),
                            constraints=[ineq_constraints, eq_constraints])
        
            if res2.success:
              
                FFF = res2.fun if res2.success else 1
                print(f"Quadratic minimize success: {res2.message}")
           
            else:
               
                success = False
                FFF = 1
                print(f"Quadratic minimize failed: {res2.message}")

            Q2 = (FF / FFF) * Q2
        
            res3 = minimize(lambda x: 0.5 * np.dot(x.T, np.dot(Q2, x)) + np.dot(f, x), x1, bounds=list(zip(lb, ub)),
                            constraints=[ineq_constraints, eq_constraints])
        
            if res3.success:
                x = res3.x
                F = res3.fun
                print(f"Final minimize success: {res3.message}")
            else:
                
                success = False
                x = x1
                F = FF
                print(f"Final minimize failed: {res3.message}")
        
        else:
            
            x = x1
            F = FF

        X = np.zeros(T)
        
        for i in range(T):
            X[i] = sum(x[3 * i:3 * (i + 1)]) - Lnoti[i]

        #print("In optimizer: X = ", X)

        return F, X, success


    def agg1(self, BL, a1, a2, nV, nL, fac):
       
        n = nV + nL
        BL = np.tile(BL, 3)
        Load = BL
        delta = 0.3
        Cars = self.cars_fields

        Xub = np.hstack((Cars['Xub'][:nV], Cars['Xub'][10000:10000 + nL]))
        Xlb = np.hstack((Cars['Xlb'][:nV], Cars['Xlb'][10000:10000 + nL]))

        Sigma = 1

        BBBat = np.hstack((Cars['BatteryCapacity'][:nV], Cars['BatteryCapacity'][10000:10000 + nL]))
        Tin = np.hstack((Cars['Tin'][:nV], Cars['Tin'][10000:10000 + nL]))
        ISOC = np.hstack((Cars['ISOC'][:nV], Cars['ISOC'][10000:10000 + nL]))
        DSOC = np.hstack((Cars['DSOC'][:nV], Cars['DSOC'][10000:10000 + nL]))
        Tout = np.hstack((Cars['Tout'][:nV], Cars['Tout'][10000:10000 + nL]))
        Tav = np.hstack((Cars['Tav'][:nV], Cars['Tav'][10000:10000 + nL]))

        T = int(max(Tout))

        print("In Agg1: T = ", T)

        BL = BL[:T]
        E1 = DSOC - ISOC
        E = E1 * BBBat
        tt = 0
        Stop = 0

        N = len(Tin)
        k = np.zeros(N)

        X0 = np.zeros((N, T))
        Xhelp = X0.copy()
        Xold = X0.copy()
        Xnew = X0.copy()
        X = np.zeros((N, T))
        XX = []
        Lnoti = np.zeros(BL.shape)
        
        for i in range(N):
     
            k[i] = abs(E[i]) / Tav[i] / ((sum(BL) / len(BL)) + sum(abs(E) / Tav))

        
        print("Starting Initial Optimization...")
        
        for i in tqdm(range(N), desc="Initial Optimization"):
            
            Lnoti = BL + np.sum(Xnew, axis=0) - Xnew[i]
           
            _, temp_X, success = self.optimizer(Lnoti, BBBat[i], ISOC[i], DSOC[i], k[i], T, Sigma, Tin[i], Tout[i], Xub[i], Xlb[i], a1, a2, delta)
           
            if success:
                
                X[i, :] = temp_X
                print("Successful Intial Optimizatation")
          
            Xnew[i, :] = X[i, :]

        Lnoti = np.zeros(BL.shape)

        print("Starting Decentralized Optimization...")

        #print("In Agg1: Lnoti = ", Lnoti)

        Lnoti = np.zeros(BL.shape)
      
        while np.linalg.norm(Xold - Xnew) > 1e-2 and tt < 5 * N:
         
            tt += 1
            
            print("Agg1: Iter = ", tt)
            print("Agg1: norm(Xold-Xnew) = ", np.linalg.norm(Xold - Xnew))
         
            for i in tqdm(range(N), desc=f"Decentralized Optimization Iter {tt}"):
              
                if not np.array_equal(Xold[i, :], Xnew[i, :]):
               
                    Lnoti = BL + np.sum(Xnew, axis=0) - Xnew[i]

                    print("In Agg1: Max of Lnoti = ", np.max(Lnoti))
                    print("In Agg1: Min of Lnoti = ", np.min(Lnoti))
                    print("In Agg1: Max of Xhelp = ", np.max(Xhelp))
                    print("In Agg1: Min of Xhelp = ", np.min(Xhelp))
                    
               
                    _, temp_X, success = self.optimizer(Lnoti, BBBat[i], ISOC[i], DSOC[i], k[i], T, Sigma, Tin[i], Tout[i], Xub[i], Xlb[i], a1, a2, delta)
                
                    if success:
                     
                        X[i, :] = temp_X
                    Xhelp[i, :] = X[i, :]
                
                else:
                 
                    Xhelp[i, :] = Xnew[i, :]

            Xold = Xnew.copy()
            Xnew = Xhelp.copy()
            XX.append(Xnew.copy())
            
            
            # Check if the program has reasced a previous state and is in a cycle
            if tt > 2:
               
                for kk in range(tt - 1):
                   
                    if np.array_equal(XX[kk], XX[tt - 1]):
                
                       Stop = 1
                       Stopkk = kk
                       
                       break
               
                if Stop == 1:
                   break


        XDec = Xnew
        TotalLoad = BL + np.sum(XDec, axis=0)
        TotalLoad = TotalLoad[23:48]
        XDec = XDec[:, 23:48]

        print("In agg1: TotalLoad = ", TotalLoad)

        return TotalLoad, XDec, Lnoti

    def agg2(self, BL, a1, a2, nV, nL, fac):
        n = nV + nL
        BL = np.tile(BL, 3)
        delta = 0.3
        Cars = self.cars_fields

        Xub = Cars['Xub']
        Xlb = Cars['Xlb']

        Sigma = 1

        BBBat = np.hstack((Cars['BatteryCapacity'][5000:5000 + nV], Cars['BatteryCapacity'][15000:15000 + nL]))
        Tin = np.hstack((Cars['Tin'][5000:5000 + nV], Cars['Tin'][15000:15000 + nL]))
        ISOC = np.hstack((Cars['ISOC'][5000:5000 + nV], Cars['ISOC'][15000:15000 + nL]))
        DSOC = np.hstack((Cars['DSOC'][5000:5000 + nV], Cars['DSOC'][15000:15000 + nL]))
        Tout = np.hstack((Cars['Tout'][5000:5000 + nV], Cars['Tout'][15000:15000 + nL]))
        Tav = np.hstack((Cars['Tav'][5000:5000 + nV], Cars['Tav'][15000:15000 + nL]))

        T = int(max(Tout))
        BL = BL[:T]
        E1 = DSOC - ISOC
        E = E1 * BBBat
        tt = 0
        Stop = 0

        N = len(Tin)
        k = np.zeros(N)

        for i in range(N):
            k[i] = abs(E[i]) / Tav[i] / ((sum(BL) / len(BL)) + sum(abs(E) / Tav))

        X0 = np.zeros((N, T))
        Xhelp = X0.copy()
        Xold = X0.copy()
        Xnew = X0.copy()
        X = np.zeros((N, T))
        XX = []

        print("Starting Initial Optimization...")
        for i in tqdm(range(N), desc="Initial Optimization"):
            Lnoti = BL + np.sum(Xnew, axis=0) - Xnew[i]
            _, temp_X, success = self.optimizer(Lnoti, BBBat[i], ISOC[i], DSOC[i], k[i], T, Sigma, Tin[i], Tout[i], Xub[i], Xlb[i], a1, a2, delta)
            if success:
                X[i, :] = temp_X
            Xnew[i, :] = X[i, :]

        print("Starting Decentralized Optimization...")
        while np.linalg.norm(Xold - Xnew) > 1e-2 and tt < 5 * N:
            tt += 1
            for i in tqdm(range(N), desc=f"Decentralized Optimization Iter {tt}"):
                if not np.array_equal(Xold[i, :], Xnew[i, :]):
                    Lnoti = BL + np.sum(Xnew, axis=0) - Xnew[i]
                    _, temp_X, success = self.optimizer(Lnoti, BBBat[i], ISOC[i], DSOC[i], k[i], T, Sigma, Tin[i], Tout[i], Xub[i], Xlb[i], a1, a2, delta)
                    if success:
                        X[i, :] = temp_X
                    Xhelp[i, :] = X[i, :]
                else:
                    Xhelp[i, :] = Xnew[i, :]

            Xold = Xnew.copy()
            Xnew = Xhelp.copy()
            XX.append(Xnew.copy())

            if tt > 2:
                for kk in range(tt - 1):
                    if np.array_equal(XX[kk], XX[tt - 1]):
                        Stop = 1
                        Stopkk = kk
                        break
                if Stop == 1:
                    break

        XDec = Xnew
        TotalLoad = BL + np.sum(XDec, axis=0)
        TotalLoad = TotalLoad[23:48]
        XDec = XDec[:, 23:48]

        print("In agg2: TotalLoad = ", TotalLoad)

        return TotalLoad, XDec

    def plot_offline(self, Load, Fig3_L):
        plt.figure(figsize=(12, 6))

        n_groups = Fig3_L.shape[0]
        bar_width = 0.25
        index = np.arange(n_groups)

        plt.bar(index, Fig3_L[0:24, 0], bar_width, color='lightgrey', label='Uncontrolled')
        plt.bar(index + bar_width, Fig3_L[0:24, 1], bar_width, color='grey', label='Agg')
        #plt.bar(index + 2 * bar_width, Fig3_L[:, 2], bar_width, color='darkgrey', label='Aggregative Game Approach')

        plt.xlabel('Time of Day (hour)')
        plt.xticks(index + bar_width, range(1, n_groups + 1))  # Adjusting the x-ticks to represent hours
        plt.xlim(-0.5, n_groups)
        plt.ylabel('Load (kWh)')
        plt.legend(loc='upper left')
        plt.title('Load Profiles')
        plt.show()

    def main(self):
        print("Starting main process...")
        fac = 0.6
        Load = fac * self.load[23:48]  # Adjust indexing for Python
        Load = Load + 0.1 * np.mean(Load) * np.random.rand(25)

        BL = Load
        a1 = 1
        a2 = 1

        print("Running agg1 for 1_1_1000...")
        L_1_1_1000, _, _ = self.agg1(BL, a1, a2, 20, 20, fac)
        #print("Running agg2 for uncont...")
        #L_uncont, X_uncont = self.agg2(BL, 1, 0, 40, 40, fac)

        Fig3_L = np.vstack((1.03 * BL, L_1_1_1000)).T
        self.plot_offline(Load, Fig3_L)
        
        print("Max BL = ", np.max(BL))
        print("Max L_1_1_1000 = ", np.max(L_1_1_1000))
      #  print("Max L_uncont = ", np.max(L_uncont))
       # print("XDec = ", X_1_1_1000)
        print("LDec = ", L_1_1_1000)
        print("Uncontrolled Load Variance: ", np.var(BL))
        print("Controlled Load Variance: ", np.var(L_1_1_1000))
        
      #  print("Lnoti = ", Lnoti_Last)
        #print("Max XDec = ", np.max(X_1_1_1000))
       # print("Min XDec = ", np.min(X_1_1_1000))
       # print("Shape of XDec = ", X_1_1_1000.shape)
        #print("Shape of XDec = ", X_1_1_1000.shape)
        print("Main process completed.")


if __name__ == "__main__":
    optimizer = LoadOptimization(r'C:\Users\14017437\Desktop\Current Projects\Papers\K - AggDRL\MATLAB Codes\CodeOcean - version 2\code\Offline Scenario\Load.mat', 
                             r'C:\Users\14017437\Desktop\Current Projects\Papers\K - AggDRL\MATLAB Codes\CodeOcean - version 2\code\Offline Scenario\Ar2_Cars_0_1_20000.mat')
    optimizer.main()

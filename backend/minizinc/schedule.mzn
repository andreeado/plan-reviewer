% === Event plan scheduling: earliest end day, one task at a time per person ===

include "disjunctive.mzn";

% === Parameters ===
int: n;                                   % number of tasks
int: UB;                                  % greedy end day
set of int: Tasks = 1..n;
array[Tasks] of int: dur;
array[Tasks] of int: owner;               % 0 = owner null, no person limit
array[Tasks] of set of Tasks: deps;
array[int] of Tasks: pair_i;              % same-owner pairs not already ordered by dependencies
array[int] of Tasks: pair_j;

% === Decision variables ===
array[Tasks] of var 0..UB: start;
var 0..UB: end_day;
array[index_set(pair_i)] of var bool: before;   % before[k] iff pair_i[k] runs before pair_j[k] (y[i,j] in the MIP)

% = Constraints =

% Every task ends by the end day
constraint forall(i in Tasks)(start[i] + dur[i] <= end_day);

% A task starts after every task it depends on
constraint forall(j in Tasks, i in deps[j])(start[j] >= start[i] + dur[i]);

% One person does one task at a time
constraint forall(o in 1..max(owner ++ [0]))(
  disjunctive([start[i] | i in Tasks where owner[i] = o],
              [dur[i]   | i in Tasks where owner[i] = o])
);

% Channeling between order variables and start times
constraint forall(k in index_set(pair_i))(
  (before[k]     -> start[pair_i[k]] + dur[pair_i[k]] <= start[pair_j[k]]) /\
  (not before[k] -> start[pair_j[k]] + dur[pair_j[k]] <= start[pair_i[k]])
);

% Decide the orderings first, then put every task at its earliest time
solve :: restart_luby(50)
      :: seq_search([bool_search(before, dom_w_deg, indomain_random, complete),
                     int_search(start, smallest, indomain_min, complete)])
      minimize end_day;

output ["{\"start\": " ++ show(start) ++ "}"];

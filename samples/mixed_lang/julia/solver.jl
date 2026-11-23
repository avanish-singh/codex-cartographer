using LinearAlgebra

struct Problem
    A::Matrix{Float64}
    b::Vector{Float64}
end

function residual(p::Problem, x::Vector{Float64})
    return norm(p.A * x - p.b)
end

function solve(p::Problem; iters::Int = 100, lr::Float64 = 0.01)
    x = zeros(length(p.b))
    for _ in 1:iters
        grad = p.A' * (p.A * x - p.b)
        x -= lr * grad
    end
    return x
end

function main()
    p = Problem([2.0 0.0; 0.0 3.0], [4.0, 9.0])
    x = solve(p)
    println("x = ", x, " residual = ", residual(p, x))
end

main()

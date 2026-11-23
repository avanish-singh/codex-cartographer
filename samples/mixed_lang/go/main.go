package main

import (
	"fmt"
	"math"
)

// Point is a 2-D sample.
type Point struct {
	X float64
	Y float64
}

// Distance returns the Euclidean distance to another point.
func (p Point) Distance(q Point) float64 {
	dx := p.X - q.X
	dy := p.Y - q.Y
	return math.Sqrt(dx*dx + dy*dy)
}

func centroid(points []Point) Point {
	var sx, sy float64
	for _, p := range points {
		sx += p.X
		sy += p.Y
	}
	n := float64(len(points))
	return Point{X: sx / n, Y: sy / n}
}

func main() {
	pts := []Point{{0, 0}, {2, 0}, {1, 2}}
	c := centroid(pts)
	fmt.Printf("centroid=(%.2f, %.2f) d0=%.2f\n", c.X, c.Y, pts[0].Distance(c))
}

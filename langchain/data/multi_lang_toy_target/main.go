// Go sibling of app.js/app.ts/UserService.java -- same shape and same
// vulnerability class. Go's bundled tree-sitter tags query has no
// class/interface scope to qualify a receiver method's name against (see
// indexer/parser.py's module docstring), so UserService.String and
// AdminService.String below are exactly the case _dedupe_names exists for.
package main

import "fmt"

func buildUserQuery(username string) string {
	// Vulnerability: string concatenation instead of a parameterized query.
	return "SELECT id, username, email FROM users WHERE username = '" + username + "'"
}

func getUserByName(username string) string {
	return buildUserQuery(username)
}

type UserService struct{}

func (s *UserService) String() string {
	return fmt.Sprintf("UserService")
}

type AdminService struct{}

func (s *AdminService) String() string {
	return fmt.Sprintf("AdminService")
}

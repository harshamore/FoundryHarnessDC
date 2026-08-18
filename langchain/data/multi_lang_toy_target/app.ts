// TypeScript sibling of app.js -- same shape, typed. Also stands in as the
// TSX-grammar fixture's source of truth (see app.tsx, which just re-exports
// through a small component wrapper).
export function buildUserQuery(username: string): string {
    // Vulnerability: string concatenation instead of a parameterized query.
    return "SELECT id, username, email FROM users WHERE username = '" + username + "'";
}

export function getUserByName(username: string): string {
    return buildUserQuery(username);
}

export class UserService {
    getUser(name: string): string {
        return getUserByName(name);
    }
}

export class AdminService {
    getUser(name: string): string {
        // Same method name as UserService.getUser -- exercises class
        // qualification the same way app.js's two controllers do.
        return getUserByName(name);
    }
}

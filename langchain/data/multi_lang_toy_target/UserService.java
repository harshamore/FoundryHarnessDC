// Java sibling of app.js/app.ts -- same shape and same vulnerability class.
public class UserService {
    public String buildUserQuery(String username) {
        // Vulnerability: string concatenation instead of a parameterized query.
        return "SELECT id, username, email FROM users WHERE username = '" + username + "'";
    }

    public String getUserByName(String username) {
        return buildUserQuery(username);
    }
}

class AdminService {
    public String getUserByName(String username) {
        // Same method name as UserService.getUserByName -- exercises class
        // qualification the same way app.js's two controllers do.
        return "admin: " + username;
    }
}

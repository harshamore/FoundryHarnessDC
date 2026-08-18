// Small deliberately-vulnerable Express-style app -- the JavaScript sibling
// of data/toy_target/vulnerable_app.py, same spirit: a couple of real
// vulnerabilities, small enough to read in one sitting.
const db = require("./db");

function buildUserQuery(username) {
    // Vulnerability: string concatenation instead of a parameterized query.
    return "SELECT id, username, email FROM users WHERE username = '" + username + "'";
}

function getUserByName(username) {
    return db.query(buildUserQuery(username));
}

class UserController {
    getUser(req, res) {
        const user = getUserByName(req.params.name);
        res.json(user);
    }

    listAdmins(req, res) {
        res.json(getUserByName("admin"));
    }
}

class AdminController {
    getUser(req, res) {
        // Same method name as UserController.getUser -- exercises class
        // qualification (UserController.getUser vs AdminController.getUser)
        // rather than colliding on a bare "getUser".
        res.json(getUserByName(req.params.name));
    }
}

module.exports = { getUserByName, buildUserQuery, UserController, AdminController };

//فایل اصلی برای اجرای پروژه:

import React from "react";
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import Swap from "../pages/Swap";
import Dashboard from "../pages/Dashboard";
import Header from "../components/Header";

function App() {
    return (
        <Router>
            <Header />
            <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/swap" element={<Swap />} />
            </Routes>
        </Router>
    );
}

export default App;

# stashboard
# 🚀 Stock Management System

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

**A comprehensive desktop application for inventory control, billing, and business reporting**  
Built with Python and Tkinter for small-to-medium businesses seeking efficient stock management.

## ✨ Key Features

- **Inventory Management**
  - Track products, brands, and suppliers
  - Low-stock alerts and expiration tracking
  - Batch management (FIFO system)
  
- **GST-Compliant Billing**
  - Automatic tax calculations (CGST/SGST/CESS)
  - Customer management with GST details
  - Professional invoice generation

- **Business Intelligence**
  - Sales reports and product performance
  - Customer purchase history
  - Stock valuation reports

- **Security**
  - Role-based access control (Admin/User)
  - Login audit trails
  - Local database encryption

## 📦 Installation & Usage

### For End Users:
1. Download latest release from [Releases](https://github.com/ISHASHWAT-SINGHI/stashboard/releases)
2. Unzip `StockManagement.zip`
3. Run `StockManagement.exe`
4. Use default credentials:  
   👨‍💼 Admin: `admin` / `admin123`  
   👩‍💼 User: Create new accounts via admin panel

### For Developers:
```bash
# Clone repository
git clone https://github.com/yourusername/stock-management.git

# Install dependencies
pip install -r requirements.txt

# Run application
python active_backup.py
🛠️ Built With
Frontend: Tkinter, ttk

Backend: Python 3.8+

Database: SQLite3

Packaging: PyInstaller
==========================================
      STOCK MANAGEMENT SYSTEM
           File Structure
==========================================

StockManagement/  👇 (Main Application Folder)
│
├── 📄 StockManagement.exe        - MAIN APPLICATION
│    │
│    └── 💡 What it does:
│         - Self-contained executable (no Python needed)
│         - Launches the stock management system
│         - Auto-creates database/log on first run
│
├── 📁 _internal/                 - APPLICATION ENGINE
│    │
│    ├── 📄 python*.dll           - Python runtime core
│    ├── 📄 tk86t.dll             - Tkinter GUI engine
│    ├── 📄 sqlite3.dll            - Database engine
│    ├── 📄 *.pyd                 - Compiled Python modules
│    └── 📁 tcl/                  - Theming/UI resources
│         ├── 📁 ttk/
│         └── 📁 fonts/
│
├── 📄 base_library.zip           - Python Standard Library
│    │
│    └── 💡 Contains:
│         - os/sys modules
│         - datetime utilities
│         - logging system
│         - SQLite interface
│
├── 📄 stock_management.db        - DATABASE FILE
│    │
│    └── 🔒 Auto-created on first run:
│         - Tables: products, companies, customers
│         - Settings: users, gst_slabs
│         - Bills: invoices, transactions
│
├── 📄 stock_management.log       - ACTIVITY LOG
│    │
│    └── 📝 Records:
│         - User logins/logouts
│         - Database operations
│         - Error reports
│         - Stock changes
│
└── 📄 README.txt                 - USER GUIDE
     │
     └── ✨ Contains:
          - Installation instructions
          - Default credentials
          - Troubleshooting
          - Support contacts

==========================================
         Key Technical Details
==========================================

1. SELF-CONTAINED ARCHITECTURE
   - No external dependencies
   - Embedded Python 3.9+ runtime
   - Portable design (runs from USB drives)

2. DATA STORAGE
   - SQLite database (single-file relational DB)
   - Automatic daily backups (within same folder)
   - CSV export capability (via Reports tab)

3. SECURITY
   - Admin/user role system
   - Password-protected access
   - Local data storage (no cloud transmission)

4. COMPATIBILITY
   - Windows 7-11 (32-bit and 64-bit)
   - Works on domain-joined PCs
   - Runs without admin privileges

5. RESOURCE USAGE
   - Disk: 50-100 MB (including database)
   - Memory: ~150 MB during operation
   - CPU: Minimal usage (single-threaded)

==========================================
         File Purpose Summary
==========================================

| File/Folder          | Type      | User-Accessible | Critical | Modifiable |
|----------------------|-----------|-----------------|----------|------------|
| StockManagement.exe  | Executable| Yes             | ★★★      | No         |
| stock_management.db  | Database  | Yes (Backup)    | ★★★      | Via App    |
| stock_management.log | Log       | Yes (Read)      | ★        | Via App    |
| README.txt           | Document  | Yes             | ★★       | Yes        |
| _internal/           | System    | No              | ★★★      | No         |
| base_library.zip     | System    | No              | ★★★      | No         |

★★★ = Critical (Don't delete/modify directly)
★★  = Important (Reference only)
★   = Optional (Can be deleted)

==========================================
    SAFETY NOTE: Windows Defender Alert
==========================================

❗ When running first time:
   Windows Defender may show "Unrecognized app" warning

✅ This is normal for unsigned applications. Choose:
   → "More info" → "Run anyway"

🔒 Safety guarantee:
   - No internet access required
   - No external connections
   - Open-source code available (provide GitHub link if applicable)

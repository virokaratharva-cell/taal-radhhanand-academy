/**
 * TAAL - Tabla Class & Music Academy Management System
 * Interactive UI behaviors
 */

document.addEventListener('DOMContentLoaded', function () {
    // 1. Mobile Sidebar & Backdrop Controls
    const sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
    const mobileMenuOpenBtn = document.getElementById('mobileMenuOpenBtn');
    const sidebarCloseBtn = document.getElementById('sidebarCloseBtn');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');
    const appSidebar = document.querySelector('.app-sidebar');

    function openSidebar() {
        if (appSidebar) appSidebar.classList.add('show');
        if (sidebarBackdrop) sidebarBackdrop.classList.add('show');
        document.body.style.overflow = 'hidden';
    }

    function closeSidebar() {
        if (appSidebar) appSidebar.classList.remove('show');
        if (sidebarBackdrop) sidebarBackdrop.classList.remove('show');
        document.body.style.overflow = '';
    }

    if (sidebarToggleBtn) {
        sidebarToggleBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            if (appSidebar && appSidebar.classList.contains('show')) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });
    }

    if (mobileMenuOpenBtn) {
        mobileMenuOpenBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            openSidebar();
        });
    }

    if (sidebarCloseBtn) {
        sidebarCloseBtn.addEventListener('click', function () {
            closeSidebar();
        });
    }

    if (sidebarBackdrop) {
        sidebarBackdrop.addEventListener('click', function () {
            closeSidebar();
        });
    }

    // Close sidebar on mobile when navigating via nav link
    if (appSidebar) {
        appSidebar.querySelectorAll('.nav-link-custom').forEach(link => {
            link.addEventListener('click', function () {
                if (window.innerWidth < 992) {
                    closeSidebar();
                }
            });
        });
    }

    // 2. Attendance Fast Marking Helpers
    const markAllPresentBtn = document.getElementById('markAllPresentBtn');
    const markAllAbsentBtn = document.getElementById('markAllAbsentBtn');

    if (markAllPresentBtn) {
        markAllPresentBtn.addEventListener('click', function () {
            const presentRadios = document.querySelectorAll('input[type="radio"][value="present"]');
            presentRadios.forEach(radio => {
                radio.checked = true;
                updateToggleBtnState(radio);
            });
        });
    }

    if (markAllAbsentBtn) {
        markAllAbsentBtn.addEventListener('click', function () {
            if (confirm("Are you sure you want to mark ALL students absent for this session?")) {
                const absentRadios = document.querySelectorAll('input[type="radio"][value="absent"]');
                absentRadios.forEach(radio => {
                    radio.checked = true;
                    updateToggleBtnState(radio);
                });
            }
        });
    }

    // Update style for status radio toggles
    function updateToggleBtnState(radio) {
        const group = radio.closest('.attendance-toggle-group');
        if (!group) return;
        const buttons = group.querySelectorAll('.attendance-toggle-btn');
        buttons.forEach(btn => {
            btn.className = 'attendance-toggle-btn';
        });
        const selectedBtn = radio.closest('.attendance-toggle-btn');
        if (selectedBtn) {
            selectedBtn.classList.add('active-' + radio.value);
        }
    }

    document.querySelectorAll('.attendance-toggle-group input[type="radio"]').forEach(radio => {
        radio.addEventListener('change', function () {
            updateToggleBtnState(this);
        });
    });

    // 3. Quick Table Search Filter
    const quickSearchInput = document.getElementById('quickTableSearch');
    if (quickSearchInput) {
        quickSearchInput.addEventListener('input', function () {
            const query = this.value.toLowerCase().trim();
            const rows = document.querySelectorAll('.filterable-table tbody tr');
            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                if (text.includes(query)) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        });
    }

    // 4. Confirmation for destructive actions
    document.querySelectorAll('[data-confirm]').forEach(el => {
        el.addEventListener('click', function (e) {
            const msg = this.getAttribute('data-confirm') || "Are you sure you want to proceed?";
            if (!confirm(msg)) {
                e.preventDefault();
            }
        });
    });
});

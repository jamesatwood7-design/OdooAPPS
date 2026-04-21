/**
 * Searchable-dropdown bootstrapping via Tom Select.
 *
 * Auto-initialises any <select class="form-select"> (or .form-select-sm) that
 * has more than 8 options. Opt OUT on a per-element basis with
 * data-no-search. Opt IN for short lists with data-searchable.
 *
 * Behaviour:
 *  - Preserves the underlying <select> so form submission keeps working.
 *  - Keeps inline onchange handlers (Tom Select dispatches a 'change' event on
 *    the original element, so handlers like onProductSelect(this, idx) still
 *    fire correctly).
 *  - Re-runs when new rows are added dynamically (MutationObserver).
 */
(function() {
    'use strict';

    var MIN_OPTIONS_FOR_SEARCH = 8;

    function shouldSearchify(sel) {
        if (!sel || sel.tagName !== 'SELECT') return false;
        if (sel.tomselect) return false;                    // already init'd
        if (sel.dataset.noSearch !== undefined) return false;
        if (sel.multiple) return false;                     // TODO: handle later
        if (!sel.classList.contains('form-select') &&
            !sel.classList.contains('form-select-sm')) return false;
        if (sel.dataset.searchable !== undefined) return true;
        return sel.options.length >= MIN_OPTIONS_FOR_SEARCH;
    }

    function searchify(sel) {
        if (!shouldSearchify(sel)) return;
        try {
            new TomSelect(sel, {
                create: false,
                allowEmptyOption: true,
                maxOptions: 1000,
                searchField: ['text'],
                plugins: { clear_button: { title: 'Clear' } },
                render: {
                    no_results: function(data) {
                        return '<div class="no-results">No matches for "' +
                               escapeHtml(data.input) + '"</div>';
                    }
                }
            });
        } catch (e) {
            // Never break a form just because Tom Select couldn't init one select.
            console && console.warn && console.warn('Tom Select init failed:', e, sel);
        }
    }

    function escapeHtml(s) {
        return String(s || '').replace(/[&<>"']/g, function(c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;',
                     '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function initAll(root) {
        (root || document).querySelectorAll('select.form-select, select.form-select-sm')
            .forEach(searchify);
    }

    document.addEventListener('DOMContentLoaded', function() {
        initAll();

        // Watch for dynamically added selects (e.g. Add New Row on invoice form).
        var mo = new MutationObserver(function(mutations) {
            mutations.forEach(function(m) {
                m.addedNodes.forEach(function(node) {
                    if (node.nodeType !== 1) return;
                    if (node.tagName === 'SELECT') {
                        searchify(node);
                    } else if (node.querySelectorAll) {
                        initAll(node);
                    }
                });
            });
        });
        mo.observe(document.body, { childList: true, subtree: true });
    });

    // Expose a helper for pages that mutate options after init (e.g. SO picker
    // that swaps the customer's option list via AJAX).
    window.refreshSearchableSelect = function(sel) {
        if (!sel) return;
        if (sel.tomselect) {
            sel.tomselect.clear(true);
            sel.tomselect.clearOptions();
            Array.from(sel.options).forEach(function(o) {
                sel.tomselect.addOption({ value: o.value, text: o.text });
            });
            sel.tomselect.refreshOptions(false);
            if (sel.value) sel.tomselect.setValue(sel.value, true);
        }
    };
})();

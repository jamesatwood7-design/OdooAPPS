/**
 * List-view filter helpers.
 *
 * The Python side (common/list_query.py) reads filter state from the URL,
 * so the JS only needs to keep the URL in sync with the form controls.
 * Every control flagged with `data-list-autosubmit` triggers a form
 * submit — debounced on text inputs so typing doesn't thrash.
 */
(function () {
    'use strict';

    var TEXT_INPUT_DEBOUNCE_MS = 300;

    function wire(form) {
        var debounceTimer = null;
        var controls = form.querySelectorAll('[data-list-autosubmit]');
        controls.forEach(function (el) {
            var isText = el.tagName === 'INPUT' &&
                (el.type === 'text' || el.type === 'search');
            var eventName = isText ? 'input' : 'change';
            el.addEventListener(eventName, function () {
                resetPage(form);
                if (isText) {
                    clearTimeout(debounceTimer);
                    debounceTimer = setTimeout(function () {
                        form.submit();
                    }, TEXT_INPUT_DEBOUNCE_MS);
                } else {
                    form.submit();
                }
            });
        });
    }

    /** Any filter change resets to page 1. */
    function resetPage(form) {
        var pageInput = form.querySelector('input[name="page"]');
        if (!pageInput) {
            pageInput = document.createElement('input');
            pageInput.type = 'hidden';
            pageInput.name = 'page';
            form.appendChild(pageInput);
        }
        pageInput.value = '1';
    }

    document.querySelectorAll('form[data-list-filter]').forEach(wire);
})();

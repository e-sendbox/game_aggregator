// Общие функции: индикатор непросмотренных ресерчей, кнопка запуска обхода
document.addEventListener('DOMContentLoaded', function () {
    loadBellBadge();
    loadBellLetsplayBadge();
    // при загрузке страницы проверяем, не идёт ли процесс (кнопки могли быть
    // заблокированы на другой странице)
    fetchRunStatus();
    initRunEvents();
    initRunModal();
    const bell = document.getElementById('bell');
    if (bell) {
        bell.addEventListener('click', function (e) {
            e.stopPropagation();
            closeBellLpPanel();
            const panel = document.getElementById('bell-panel');
            const isOpen = panel.classList.contains('open');
            closeBellPanel();
            if (!isOpen) {
                panel.classList.add('open');
                loadResearches();
            }
        });
        document.addEventListener('click', closeBellPanel);
    }
    const bellLp = document.getElementById('bell-lp');
    if (bellLp) {
        bellLp.addEventListener('click', function (e) {
            e.stopPropagation();
            closeBellPanel();
            const panel = document.getElementById('bell-lp-panel');
            const isOpen = panel.classList.contains('open');
            closeBellLpPanel();
            if (!isOpen) {
                panel.classList.add('open');
                loadResearchesLetsplay();
            }
        });
        document.addEventListener('click', closeBellLpPanel);
    }
    initLetsplayModal();
});

// ===== Попап «Запуск ресерча игр» (шаг 9) =====
function initRunModal() {
    const runBtn = document.getElementById('run-btn');
    const modal = document.getElementById('run-modal');
    if (!runBtn || !modal) return;

    runBtn.addEventListener('click', function () {
        modal.classList.add('open');
        loadRunHints();
    });
    document.getElementById('run-modal-close').addEventListener('click', function () {
        modal.classList.remove('open');
    });
    modal.addEventListener('click', function (e) {
        if (e.target === modal) modal.classList.remove('open');
    });

    // Подстановка подсказок: окно в опции reset, дата последнего ресерча в опции check
    function loadRunHints() {
        fetch('/api/settings')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                const resetHint = document.getElementById('run-reset-hint');
                if (resetHint) {
                    const labels = { '1': 'за сегодня', '2': 'со вчера', '3': 'с позавчера' };
                    resetHint.textContent = labels[data.days_back] || 'за сегодня';
                }
                const checkHint = document.getElementById('run-check-hint');
                if (checkHint) {
                    checkHint.textContent = data.last_research_at || '(ресерчей сегодня не было)';
                }
            })
            .catch(function () {});
    }

    document.getElementById('run-modal-run').addEventListener('click', function () {
        const mode = document.querySelector('input[name="run-mode"]:checked').value;
        modal.classList.remove('open');
        fetch('/api/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: mode }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.status === 'started') {
                    setRunButtonsLocked(true, '«Поиск обновлений»');
                } else {
                    alert(data.message);
                }
            })
            .catch(function () {
                alert('Ошибка запуска');
            });
    });
}

// ===== Попап «Обновить летсплеи» =====
function initLetsplayModal() {
    const lpBtn = document.getElementById('lp-btn');
    const modal = document.getElementById('lp-modal');
    if (!lpBtn || !modal) return;

    lpBtn.addEventListener('click', function () {
        modal.classList.add('open');
        loadLetsplayModal();
    });
    document.getElementById('lp-modal-close').addEventListener('click', function () {
        modal.classList.remove('open');
    });
    modal.addEventListener('click', function (e) {
        if (e.target === modal) modal.classList.remove('open');
    });

    const researchCheck = document.getElementById('lp-research-check');
    researchCheck.addEventListener('change', function () {
        const ids = researchCheck.dataset.ids ? researchCheck.dataset.ids.split(',') : [];
        document.querySelectorAll('.lp-game-check').forEach(function (cb) {
            if (ids.includes(cb.value)) cb.checked = researchCheck.checked;
        });
    });

    document.getElementById('lp-run-btn').addEventListener('click', function () {
        const selected = [];
        document.querySelectorAll('.lp-game-check:checked').forEach(function (cb) {
            selected.push(cb.value);
        });
        if (!selected.length) {
            alert('Не выбрано ни одной игры');
            return;
        }
        // закрываем попап сразу, до ответа сервера
        modal.classList.remove('open');
        fetch('/api/letsplay/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_ids: selected }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.status === 'started') {
                    setRunButtonsLocked(true, '«Поиск летсплеев»');
                } else {
                    alert(data.message);
                }
            })
            .catch(function () {
                alert('Ошибка запуска');
            });
    });
}

// Блокировка кнопок запуска на время выполнения процесса
function setRunButtonsLocked(locked, process) {
    const lpBtn = document.getElementById('lp-btn');
    const runBtn = document.getElementById('run-btn');
    const hint = locked
        ? 'действия недоступны, запущен ресерч ' + process + ', дождись окончания'
        : null;    if (lpBtn) {
        lpBtn.disabled = locked;
        lpBtn.title = hint || 'Обновить летсплеи';
    }
    if (runBtn) {
        runBtn.disabled = locked;
        runBtn.title = hint || 'Загрузить игровые обновления';
    }
}

// Начальное состояние: один быстрый fetch (пока SSE-соединение устанавливается)
function fetchRunStatus() {
    fetch('/api/run/status')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            setRunButtonsLocked(data.busy, data.process || 'неизвестный процесс');
        })
        .catch(function () {});
}

// SSE: сервер сам пушит события запуска/завершения процесса (без опроса)
function initRunEvents() {
    const source = new EventSource('/api/events');
    source.onmessage = function (e) {
        try {
            const data = JSON.parse(e.data);
            setRunButtonsLocked(data.busy, data.process || 'неизвестный процесс');
            if (!data.busy) {
                // процесс завершился → обновить бейджи колокольчиков
                loadBellBadge();
                loadBellLetsplayBadge();
                // финальная подтяжка логов: отбивка могла не успеть записаться
                setTimeout(function () {
                    loadLogs(logsActiveTab, true);
                }, 800);
            }
        } catch (err) {}
    };
    // EventSource переподключается сам при обрыве
}

function loadLetsplayModal() {
    const grid = document.getElementById('lp-games-grid');
    const label = document.getElementById('lp-research-label');
    const researchCheck = document.getElementById('lp-research-check');
    grid.innerHTML = 'Загрузка...';

    Promise.all([
        fetch('/api/games').then(function (r) { return r.json(); }),
        fetch('/api/research-games').then(function (r) { return r.json(); }),
    ]).then(function (results) {
        const allGames = results[0];
        const research = results[1];
        if (research.message) {
            label.textContent = 'Игры последнего ресерча: ' + research.message;
            researchCheck.dataset.ids = '';
        } else {
            const titles = research.games.map(function (g) { return g.title; }).join(', ');
            label.textContent = 'Игры последнего ресерча: ' + titles;
            researchCheck.dataset.ids = research.games.map(function (g) { return g.id; }).join(',');
        }
        grid.innerHTML = '';
        allGames.forEach(function (g) {
            const item = document.createElement('label');
            item.className = 'lp-game-item';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'lp-game-check';
            cb.value = g.id;
            item.appendChild(cb);
            item.appendChild(document.createTextNode(' ' + g.title));
            grid.appendChild(item);
        });
    }).catch(function () {
        grid.innerHTML = 'Ошибка загрузки';
    });
}

// Бейдж на колокольчике: количество непросмотренных ресерчей
function loadBellBadge() {
    fetch('/api/bell')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            const badge = document.getElementById('bell-badge');
            if (badge) badge.textContent = data.count;
        })
        .catch(function () {});
}

function closeBellPanel() {
    const panel = document.getElementById('bell-panel');
    if (panel) panel.classList.remove('open');
}

// Список ресерчей в панельке
function loadResearches() {
    const list = document.getElementById('bell-panel-list');
    if (!list) return;
    list.innerHTML = 'Загрузка...';
    fetch('/api/researches')
        .then(function (r) { return r.json(); })
        .then(function (rows) {
            if (!rows.length) {
                list.innerHTML = '<div class="bell-row">Ресерчей нет</div>';
                return;
            }
            list.innerHTML = '';
            rows.forEach(function (r) {
                const row = document.createElement('div');
                row.className = 'bell-row' + (r.people_processed ? ' processed' : '');
                const link = document.createElement('a');
                link.className = 'bell-link';
                link.href = '/?research=' + r.id;
                link.textContent = r.started_at + ' · выпущено игр: ' + r.new_count;
                link.addEventListener('click', function () {
                    markProcessed(r.id);
                });
                row.appendChild(link);
                if (r.unsuccess_count > 0) {
                    const errLink = document.createElement('a');
                    errLink.className = 'bell-link bell-errors';
                    errLink.href = '/?unsuccess=' + r.id;
                    errLink.textContent = '(есть ошибки: ' + r.unsuccess_count + ')';
                    errLink.addEventListener('click', function () {
                        markProcessed(r.id);
                    });
                    row.appendChild(errLink);
                }
                const mark = document.createElement('span');
                if (r.people_processed) {
                    mark.className = 'bell-mark done';
                    mark.textContent = '✓';
                    mark.title = 'Обработан';
                } else {
                    mark.className = 'bell-mark';
                    mark.textContent = '✕';
                    mark.title = 'Отметить обработанным';
                    mark.addEventListener('click', function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        markProcessed(r.id);
                    });
                }
                row.appendChild(mark);
                list.appendChild(row);
            });
        })
        .catch(function () { list.innerHTML = 'Ошибка загрузки'; });
}

// Отметить ресерч обработанным
function markProcessed(id) {
    fetch('/api/researches/' + id + '/processed', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function () {
            loadResearches();
            loadBellBadge();
        })
        .catch(function () {});
}

// ===== Второй колокольчик: ресерчи летсплеев =====
function loadBellLetsplayBadge() {
    fetch('/api/bell-letsplay')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            const badge = document.getElementById('bell-lp-badge');
            if (badge) badge.textContent = data.count;
        })
        .catch(function () {});
}

function closeBellLpPanel() {
    const panel = document.getElementById('bell-lp-panel');
    if (panel) panel.classList.remove('open');
}

function loadResearchesLetsplay() {
    const list = document.getElementById('bell-lp-panel-list');
    if (!list) return;
    list.innerHTML = 'Загрузка...';
    fetch('/api/researches-letsplay')
        .then(function (r) { return r.json(); })
        .then(function (rows) {
            if (!rows.length) {
                list.innerHTML = '<div class="bell-row">Ресерчей летсплеев нет</div>';
                return;
            }
            list.innerHTML = '';
            rows.forEach(function (r) {
                const row = document.createElement('div');
                row.className = 'bell-row' + (r.people_processed ? ' processed' : '');
                const link = document.createElement('a');
                link.className = 'bell-link';
                link.href = '/?research_letsplay=' + r.id;
                link.textContent = r.started_at + ' · игр: ' + r.game_count;
                link.addEventListener('click', function () {
                    markLetsplayProcessed(r.id);
                });
                row.appendChild(link);
                if (r.fail_count > 0) {
                    const errLink = document.createElement('a');
                    errLink.className = 'bell-link bell-errors';
                    errLink.href = '/?research_letsplay=' + r.id + '&fail=1';
                    errLink.textContent = '(есть ошибки: ' + r.fail_count + ')';
                    errLink.addEventListener('click', function () {
                        markLetsplayProcessed(r.id);
                    });
                    row.appendChild(errLink);
                }
                const mark = document.createElement('span');
                if (r.people_processed) {
                    mark.className = 'bell-mark done';
                    mark.textContent = '✓';
                    mark.title = 'Обработан';
                } else {
                    mark.className = 'bell-mark';
                    mark.textContent = '✕';
                    mark.title = 'Отметить обработанным';
                    mark.addEventListener('click', function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        markLetsplayProcessed(r.id);
                    });
                }
                row.appendChild(mark);
                list.appendChild(row);
            });
        })
        .catch(function () { list.innerHTML = 'Ошибка загрузки'; });
}

function markLetsplayProcessed(id) {
    fetch('/api/researches-letsplay/' + id + '/processed', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function () {
            loadResearchesLetsplay();
            loadBellLetsplayBadge();
        })
        .catch(function () {});
}

// ===== Список игр: фильтры и сортировки через query-параметры =====
function applyFilters() {
    const params = new URLSearchParams(window.location.search);
    const search = document.getElementById('search-input').value.trim().toLowerCase();
    const platform = document.getElementById('platform-filter').value;
    if (search) params.set('search', search); else params.delete('search');
    if (platform) params.set('platform', platform); else params.delete('platform');
    window.location.search = params.toString();
}

// Поиск: срабатывает только по Enter; при очистке строки — показываем все игры
document.addEventListener('DOMContentLoaded', function () {
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                applyFilters();
            }
        });
        searchInput.addEventListener('input', function () {
            if (searchInput.value.trim() === '') {
                applyFilters();
            }
        });
        // после перезагрузки страницы (Enter/очистка) возвращаем фокус в строку поиска
        searchInput.focus();
        searchInput.setSelectionRange(searchInput.value.length, searchInput.value.length);
    }
    const platformFilter = document.getElementById('platform-filter');
    if (platformFilter) {
        platformFilter.addEventListener('change', applyFilters);
    }

    // Пагинация: кнопки ← → меняют ?page=N (перезагрузка — серверная нарезка)
    document.querySelectorAll('.page-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const params = new URLSearchParams(window.location.search);
            params.set('page', btn.dataset.page);
            window.location.search = params.toString();
        });
    });

    // Кнопки сортировки: клик → ?sort=<name>_asc|desc (переключение направления)
    // Сортировка выполняется ЛОКАЛЬНО (без перезагрузки страницы), URL обновляется через
    // history.replaceState — при F5 сервер отрендерит список в том же порядке.
    const sortButtons = [
        ['sort-all-metascore', 'all_metascore'],
        ['sort-all-userscore', 'all_userscore'],
    ];
    function scoreValue(tile, name) {
        const attr = name === 'all_metascore' ? 'data-metascore' : 'data-userscore';
        const v = parseFloat(tile.getAttribute(attr));
        return isNaN(v) ? -1 : v;
    }
    let originalOrder = null;
    function sortGrid(name, dir) {
        const grid = document.getElementById('games-grid');
        if (!grid) return;
        if (originalOrder === null) {
            originalOrder = Array.prototype.slice.call(grid.querySelectorAll('.game-tile'));
        }
        if (name === null) {
            // сброс: возвращаем исходный порядок сервера
            originalOrder.forEach(function (t) { grid.appendChild(t); });
            return;
        }
        const tiles = Array.prototype.slice.call(grid.querySelectorAll('.game-tile'));
        tiles.sort(function (a, b) {
            const va = scoreValue(a, name);
            const vb = scoreValue(b, name);
            // tbd (нет скора) всегда в конце, независимо от направления
            if (va < 0 && vb < 0) return 0;
            if (va < 0) return 1;
            if (vb < 0) return -1;
            const d = va - vb;
            return dir === 'desc' ? -d : d;
        });
        tiles.forEach(function (t) { grid.appendChild(t); });
    }
    sortButtons.forEach(function (pair) {
        const btn = document.getElementById(pair[0]);
        if (!btn) return;
        // фиксируем, был ли фокус в поиске ДО смены фокуса на кнопку (mousedown раньше click)
        btn.addEventListener('mousedown', function () {
            btn.dataset.searchFocused = (searchInput && document.activeElement === searchInput) ? '1' : '0';
        });
        btn.addEventListener('click', function () {
            const wasSearchFocused = btn.dataset.searchFocused === '1';
            const params = new URLSearchParams(window.location.search);
            const name = pair[1];
            const current = params.get('sort');
            let next;
            if (current === name + '_asc') {
                next = name + '_desc';
            } else if (current === name + '_desc') {
                next = null;
            } else {
                next = name + '_asc';
            }
            if (next) {
                params.set('sort', next);
                sortGrid(name, next.endsWith('_desc') ? 'desc' : 'asc');
            } else {
                params.delete('sort');
                sortGrid(null); // сброс: возвращаем исходный порядок сервера
            }
            history.replaceState(null, '', '?' + params.toString());
            // подсветка активной кнопки и стрелки без перезагрузки
            sortButtons.forEach(function (p) {
                const b = document.getElementById(p[0]);
                const arrow = b ? b.querySelector('.sort-arrow') : null;
                if (b) b.classList.remove('active');
                if (arrow) arrow.textContent = '';
            });
            if (next) {
                btn.classList.add('active');
                const arrow = btn.querySelector('.sort-arrow');
                if (arrow) arrow.textContent = next.endsWith('_asc') ? '↑' : '↓';
            }
            // возвращаем фокус в поиск, если он был там до клика
            if (wasSearchFocused && searchInput) {
                searchInput.focus();
                searchInput.setSelectionRange(searchInput.value.length, searchInput.value.length);
            }
        });
    });
});

// ===== Логи на странице настроек: глобальные функции (для финальной подтяжки после процесса) =====
let logsActiveTab = 'activity';
let logsLoading = false;
let logsViewEl = null;

function loadLogs(tab, manual) {
    const runBtn = document.getElementById('run-btn');
    const busy = runBtn && runBtn.disabled;
    if (!busy && !manual) return;
    if (logsLoading) return;
    logsLoading = true;
    if (logsViewEl) logsViewEl.classList.add('loading');
    const url = tab === 'activity'
        ? '/api/activity?limit=200'
        : '/api/logs?limit=50';
    fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            const lines = tab === 'activity'
                ? (data.activity || [])
                : (data[tab] || []);
            if (logsViewEl) {
                logsViewEl.textContent = lines.join('\n') || '(пусто)';
                if (busy) logsViewEl.scrollTop = logsViewEl.scrollHeight;
            }
        })
        .catch(function () {})
        .finally(function () {
            logsLoading = false;
            if (logsViewEl) logsViewEl.classList.remove('loading');
        });
}

// ===== Настройки: LLM + ресерчи + логи (шаг 14) =====
document.addEventListener('DOMContentLoaded', function () {
    const saveBtn = document.getElementById('save-key-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', function () {
            const apiKey = document.getElementById('ollama-key').value;
            const model = document.getElementById('ollama-model').value;
            const daysBack = document.getElementById('days-back').value;
            const analyzeLimit = document.getElementById('analyze-limit').value;
            const letsplayMonths = document.getElementById('letsplay-months').value;
            fetch('/api/ollama/check', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    api_key: apiKey,
                    model: model,
                    days_back: daysBack,
                    analyze_limit: analyzeLimit,
                    letsplay_months: letsplayMonths,
                }),
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    showCheckModal(data.checks || [], data.status, data.message);
                });
        });
    }

    // Бегунки: подпись значения + пояснение для days_back
    function bindRange(id, valueId, hintId) {
        const input = document.getElementById(id);
        const valueEl = document.getElementById(valueId);
        if (!input || !valueEl) return;
        input.addEventListener('input', function () {
            valueEl.textContent = input.value;
            if (hintId) updateDaysBackHint(input.value);
        });
    }
    function updateDaysBackHint(value) {
        const hint = document.getElementById('days-back-hint');
        if (!hint) return;
        const labels = { '1': '1 = сегодня', '2': '2 = со вчера', '3': '3 = с позавчера' };
        hint.textContent = labels[value] || '';
    }
    bindRange('days-back', 'days-back-value', 'days-back-hint');
    bindRange('analyze-limit', 'analyze-limit-value', null);
    bindRange('letsplay-months', 'letsplay-months-value', null);
    const daysBackInput = document.getElementById('days-back');
    if (daysBackInput) updateDaysBackHint(daysBackInput.value);

    // Модальное окно со статусом проверок
    const modal = document.getElementById('check-modal');
    if (modal) {
        document.getElementById('check-modal-close').addEventListener('click', function () {
            modal.classList.remove('open');
        });
        modal.addEventListener('click', function (e) {
            if (e.target === modal) modal.classList.remove('open');
        });
    }
    function showCheckModal(checks, status, message) {
        if (!modal) return;
        const list = document.getElementById('check-modal-list');
        list.innerHTML = '';
        checks.forEach(function (check) {
            const row = document.createElement('div');
            row.className = 'check-row ' + (check.ok ? 'ok' : 'fail');
            const icon = document.createElement('span');
            icon.className = 'check-icon';
            icon.textContent = check.ok ? '✓' : '✕';
            const text = document.createElement('span');
            text.textContent = check.name + (check.message ? ' — ' + check.message : '');
            row.appendChild(icon);
            row.appendChild(text);
            list.appendChild(row);
        });
        const summary = document.createElement('div');
        summary.className = 'check-summary ' + (status === 'ok' ? 'ok' : 'fail');
        summary.textContent = message || (status === 'ok' ? 'Настройки сохранены' : 'Ошибка сохранения');
        list.appendChild(summary);
        modal.classList.add('open');
    }

    const logsView = document.getElementById('logs-view');
    if (logsView) {
        logsViewEl = logsView;
        const activeTabEl = document.querySelector('.log-tab.active');
        logsActiveTab = activeTabEl ? activeTabEl.dataset.tab : 'activity';

        const tabs = document.querySelectorAll('.log-tab');
        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                tabs.forEach(function (t) { t.classList.remove('active'); });
                tab.classList.add('active');
                logsActiveTab = tab.dataset.tab;
                loadLogs(logsActiveTab, true);
            });
        });
        loadLogs(logsActiveTab, true);
        setInterval(function () {
            loadLogs(logsActiveTab);
        }, 3000);
    }
});

// ===== Форматирование текстов LLM (суммаризации, летсплеи) =====
// Универсальный мини-парсер: **Заголовок:** → раздел, "- " → список, **жирный** → strong.
function renderMarkdown(el) {
    if (!el) return;
    var raw = el.textContent || '';
    el.textContent = '';
    var lines = raw.split('\n');
    var inList = false;
    function closeList() {
        if (inList) {
            el.appendChild(document.createElement('ul'));
            el.lastChild.style.listStyle = 'disc';
            el.lastChild.style.margin = '4px 0 8px 18px';
            inList = false;
        }
    }
    lines.forEach(function (line) {
        var text = line.trim();
        if (!text) return;
        // маркированный список: "- ", "• ", "* " (в т.ч. "* **жирный**")
        if (text.indexOf('- ') === 0 || text.indexOf('• ') === 0 || text.indexOf('* ') === 0) {
            var li = document.createElement('li');
            appendRichText(li, text.replace(/^[-•*]\s+/, ''));
            if (!inList) {
                var ul = document.createElement('ul');
                ul.style.listStyle = 'disc';
                ul.style.margin = '4px 0 8px 18px';
                el.appendChild(ul);
                inList = true;
            }
            el.lastChild.appendChild(li);
            return;
        }
        closeList();
        // заголовок раздела: "**Текст:**", "### Текст:", "## Текст" или "Текст:" (короткая строка)
        var heading = null;
        var hm = text.match(/^\*\*(.+?)\*\*\s*:?\s*$/);
        if (hm) heading = hm[1];
        else {
            var hmd = text.match(/^#{1,6}\s+(.+?)\s*:?\s*$/);
            if (hmd) heading = hmd[1];
            else if (text.length < 60 && text.indexOf(':') === text.length - 1) heading = text.slice(0, -1);
        }
        if (heading) {
            var h = document.createElement('strong');
            h.textContent = heading + ':';
            h.style.display = 'block';
            h.style.marginTop = '8px';
            el.appendChild(h);
            return;
        }
        // обычная строка с **жирным** внутри
        var p = document.createElement('div');
        p.style.margin = '4px 0';
        appendRichText(p, text);
        el.appendChild(p);
    });
    closeList();
}

// Разбор строки: **жирный** → <strong>, остальное — текст
function appendRichText(container, text) {
    var parts = text.split(/\*\*(.+?)\*\*/g);
    for (var i = 0; i < parts.length; i++) {
        if (i % 2 === 1) {
            var b = document.createElement('strong');
            b.textContent = parts[i];
            container.appendChild(b);
        } else if (parts[i]) {
            container.appendChild(document.createTextNode(parts[i]));
        }
    }
}

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.md-render').forEach(function (el) {
        renderMarkdown(el);
    });
});

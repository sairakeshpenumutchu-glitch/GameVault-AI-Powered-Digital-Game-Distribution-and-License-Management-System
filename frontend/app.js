// GameVault Frontend Core Controller
// Direct Base Games + DLCs, P2P Resale Marketplace, Single-Seat DRM Concurrency Detection, DB Inspector

let state = {
  currentUserId: 1,
  users: [],
  user: null,
  games: [],
  library: [],
  marketplace: [],
  activeView: 'store',
  activeGameModal: null,
  activeDbTable: 'license_keys',
  checkoutState: null,
  activeConflictGameId: null,
  activeConflictDevice: null,
  activeSellItem: null
};

// ----------------- Initialization -----------------
document.addEventListener('DOMContentLoaded', async () => {
  await fetchUsers();
  await fetchGames();
  await fetchLibrary();
  await fetchMarketplace();
  fetchDbStats();
});

// ----------------- Navigation -----------------
function switchView(viewName) {
  state.activeView = viewName;

  document.querySelectorAll('.view-section').forEach(sec => sec.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));

  const targetView = document.getElementById(`view-${viewName}`);
  const targetNav = document.getElementById(`nav-${viewName}`);
  if (targetView) targetView.classList.add('active');
  if (targetNav) targetNav.classList.add('active');

  if (viewName === 'database') {
    fetchDbStats();
    loadTable(state.activeDbTable);
  } else if (viewName === 'library') {
    fetchLibrary();
  } else if (viewName === 'marketplace') {
    fetchMarketplace();
  } else if (viewName === 'store') {
    fetchGames();
  }
}

// ----------------- User Accounts & Switching -----------------
async function fetchUsers() {
  try {
    const res = await fetch('/api/users');
    if (!res.ok) throw new Error("Failed to load users");
    state.users = await res.json();

    const switcher = document.getElementById('user-switcher');
    if (switcher) {
      switcher.innerHTML = state.users.map(u => 
        `<option value="${u.user_id}" ${u.user_id === state.currentUserId ? 'selected' : ''}>
          ${u.username} ($${u.wallet_balance.toFixed(2)})
        </option>`
      ).join('');
    }

    await fetchUserProfile();
  } catch (err) {
    console.error("Users list error:", err);
  }
}

async function changeActiveUser(newUserId) {
  state.currentUserId = parseInt(newUserId, 10);
  await fetchUserProfile();
  await fetchLibrary();
  await fetchMarketplace();
  fetchDbStats();

  if (state.activeGameModal) {
    openGameModal(state.activeGameModal.game_id);
  }

  if (state.activeView === 'database') {
    loadTable(state.activeDbTable);
  }

  showToast(`Switched active account to ${state.user ? state.user.username : 'User #' + state.currentUserId}`, "info");
}

async function fetchUserProfile() {
  try {
    const res = await fetch(`/api/user?user_id=${state.currentUserId}`);
    if (!res.ok) throw new Error("Failed to load user");
    state.user = await res.json();

    const walletEl = document.getElementById('user-wallet');
    const avatarEl = document.getElementById('user-avatar');
    const switcher = document.getElementById('user-switcher');

    if (walletEl) walletEl.textContent = `$${state.user.wallet_balance.toFixed(2)}`;
    if (avatarEl && state.user.avatar_url) avatarEl.src = state.user.avatar_url;
    if (switcher) switcher.value = String(state.currentUserId);
  } catch (err) {
    console.error("User profile error:", err);
  }
}

async function topUpWallet() {
  try {
    const res = await fetch('/api/user/topup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: state.currentUserId, amount: 50.0 })
    });
    const data = await res.json();
    if (res.ok) {
      showToast("+$50.00 added to wallet", "success");
      await fetchUserProfile();
      await fetchUsers();
      if (state.activeView === 'database') loadTable(state.activeDbTable);
    }
  } catch (err) {
    showToast("Top-up failed", "error");
  }
}

// ----------------- Store Catalog -----------------
async function fetchGames() {
  try {
    const res = await fetch('/api/games');
    if (!res.ok) throw new Error("Failed to load games");
    state.games = await res.json();
    renderGamesGrid(state.games);
  } catch (err) {
    console.error("Games catalog error:", err);
    showToast("Failed to load store catalog", "error");
  }
}

function renderGamesGrid(gamesList) {
  const container = document.getElementById('games-grid-container');
  if (!container) return;
  container.innerHTML = '';

  if (!gamesList || gamesList.length === 0) {
    container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 4rem;">No games match your search.</div>`;
    return;
  }

  gamesList.forEach(game => {
    const card = document.createElement('div');
    card.className = 'game-card';
    card.onclick = () => openGameModal(game.game_id);

    let stockClass = 'in-stock';
    let stockText = `${game.available_keys_count} Keys In Stock`;

    if (game.available_keys_count === 0) {
      stockClass = 'low-stock';
      stockText = 'Sold Out';
    } else if (game.available_keys_count === 1) {
      stockClass = 'single-stock';
      stockText = `<span class="stock-num-red">1</span> Key In Stock`;
    }

    card.innerHTML = `
      <div class="game-card-img-wrap">
        <img class="game-card-img" src="${game.cover_image}" alt="${game.title}" loading="lazy">
        <div class="metascore-badge">${game.metascore}</div>
      </div>
      <div class="game-card-body">
        <div class="game-genre">${game.genre}</div>
        <div class="game-title">${game.title}</div>
        <div class="game-tagline">${game.tagline || ''}</div>
        <div class="game-card-footer">
          <div>
            <div class="price-tag">$${game.base_price.toFixed(2)}</div>
            <div class="stock-tag ${stockClass}">${stockText}</div>
          </div>
          <button class="btn-details">View & Buy DLCs</button>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

function filterGames() {
  const query = document.getElementById('store-search').value.toLowerCase().trim();
  const filtered = state.games.filter(g => 
    g.title.toLowerCase().includes(query) || 
    g.genre.toLowerCase().includes(query) ||
    g.developer.toLowerCase().includes(query)
  );
  renderGamesGrid(filtered);
}

// ----------------- Game Modal & DLCs Bundle Builder -----------------
async function openGameModal(gameId) {
  try {
    const res = await fetch(`/api/games/${gameId}?user_id=${state.currentUserId}`);
    if (!res.ok) throw new Error("Could not load details");
    const game = await res.json();
    state.activeGameModal = game;

    state.checkoutState = {
      gameId: game.game_id,
      basePrice: game.base_price,
      isBaseOwned: game.is_owned,
      includeBase: !game.is_owned,
      dlcs: game.dlcs || [],
      selectedDlcIds: new Set()
    };

    document.getElementById('modal-hero-img').src = game.header_image || game.cover_image;
    document.getElementById('modal-title').textContent = game.title;
    document.getElementById('modal-genre').textContent = game.genre;
    document.getElementById('modal-developer').textContent = game.developer;
    document.getElementById('modal-publisher').textContent = game.publisher_name;
    document.getElementById('modal-release').textContent = game.release_date;
    document.getElementById('modal-desc').textContent = game.description;

    const baseContainer = document.getElementById('modal-base-game-container');
    const isOutOfStock = game.in_stock_keys === 0 && !game.is_owned;

    baseContainer.innerHTML = `
      <div class="base-game-card ${state.checkoutState.includeBase ? 'selected' : ''}" 
           id="card-base-game" 
           onclick="toggleBaseGameSelection()">
        <div class="item-check-left">
          <input type="checkbox" class="custom-checkbox" id="check-base-game" 
                 ${state.checkoutState.includeBase ? 'checked' : ''} 
                 ${game.is_owned || isOutOfStock ? 'disabled' : ''} 
                 onclick="event.stopPropagation(); toggleBaseGameSelection()">
          <div class="item-main-details">
            <div class="item-title-row">
              <span class="item-title">${game.title} (Base Game)</span>
              <span class="item-badge">${game.is_owned ? 'In Library' : (isOutOfStock ? 'Out of Stock' : 'Digital License')}</span>
            </div>
            <span class="item-desc">${game.is_owned ? 'You already own this base game license.' : 'Required digital license to activate and play any child DLCs.'}</span>
          </div>
        </div>
        <div class="item-price">
          ${game.is_owned ? '<span style="color: var(--accent-green); font-size: 1rem;">Owned</span>' : `$${game.base_price.toFixed(2)}`}
        </div>
      </div>
    `;

    renderDlcsList();
    updateCheckoutSummary();

    document.getElementById('game-modal-overlay').classList.add('active');
  } catch (err) {
    showToast("Failed to load game details", "error");
  }
}

function renderDlcsList() {
  const dlcsContainer = document.getElementById('modal-dlcs-container');
  if (!dlcsContainer) return;
  dlcsContainer.innerHTML = '';

  const dlcs = state.checkoutState.dlcs;
  if (!dlcs || dlcs.length === 0) {
    dlcsContainer.innerHTML = `<div style="color: var(--text-dim); font-size: 0.85rem; padding: 1rem 0;">No separate DLC expansions available for this title.</div>`;
    return;
  }

  dlcs.forEach(dlc => {
    const isSelected = state.checkoutState.selectedDlcIds.has(dlc.dlc_id);
    const card = document.createElement('div');
    card.className = `dlc-selectable-card ${isSelected ? 'selected' : ''} ${dlc.is_owned ? 'owned' : ''}`;
    card.id = `dlc-card-${dlc.dlc_id}`;

    if (!dlc.is_owned) {
      card.onclick = () => toggleDlcSelection(dlc.dlc_id);
    }

    card.innerHTML = `
      <div class="item-check-left">
        <input type="checkbox" class="custom-checkbox" id="check-dlc-${dlc.dlc_id}"
               ${isSelected ? 'checked' : ''}
               ${dlc.is_owned ? 'disabled' : ''}
               onclick="event.stopPropagation(); toggleDlcSelection(${dlc.dlc_id})">
        <div class="item-main-details">
          <div class="item-title-row">
            <span class="item-title">${dlc.title}</span>
            <span class="item-badge" style="color: var(--accent-amber);">${dlc.dlc_type}</span>
          </div>
          <span class="item-desc">${dlc.description}</span>
        </div>
      </div>
      <div class="item-price">
        ${dlc.is_owned ? '<span style="color: var(--accent-green); font-size: 0.95rem;">Owned</span>' : `$${dlc.price.toFixed(2)}`}
      </div>
    `;
    dlcsContainer.appendChild(card);
  });

  updateSelectAllButtonState();
}

function toggleBaseGameSelection() {
  if (state.checkoutState.isBaseOwned) return;
  state.checkoutState.includeBase = !state.checkoutState.includeBase;

  const chk = document.getElementById('check-base-game');
  if (chk) chk.checked = state.checkoutState.includeBase;

  const card = document.getElementById('card-base-game');
  if (card) {
    if (state.checkoutState.includeBase) card.classList.add('selected');
    else card.classList.remove('selected');
  }

  updateCheckoutSummary();
}

function toggleDlcSelection(dlcId) {
  if (state.checkoutState.selectedDlcIds.has(dlcId)) {
    state.checkoutState.selectedDlcIds.delete(dlcId);
  } else {
    state.checkoutState.selectedDlcIds.add(dlcId);
  }

  const chk = document.getElementById(`check-dlc-${dlcId}`);
  if (chk) chk.checked = state.checkoutState.selectedDlcIds.has(dlcId);

  const card = document.getElementById(`dlc-card-${dlcId}`);
  if (card) {
    if (state.checkoutState.selectedDlcIds.has(dlcId)) card.classList.add('selected');
    else card.classList.remove('selected');
  }

  updateSelectAllButtonState();
  updateCheckoutSummary();
}

function toggleSelectAllDlcs() {
  const unownedDlcs = state.checkoutState.dlcs.filter(d => !d.is_owned);
  if (unownedDlcs.length === 0) return;

  const allSelected = unownedDlcs.every(d => state.checkoutState.selectedDlcIds.has(d.dlc_id));

  if (allSelected) {
    unownedDlcs.forEach(d => state.checkoutState.selectedDlcIds.delete(d.dlc_id));
  } else {
    unownedDlcs.forEach(d => state.checkoutState.selectedDlcIds.add(d.dlc_id));
  }

  renderDlcsList();
  updateCheckoutSummary();
}

function updateSelectAllButtonState() {
  const btn = document.getElementById('btn-toggle-all-dlcs');
  if (!btn) return;
  const unownedDlcs = state.checkoutState.dlcs.filter(d => !d.is_owned);
  if (unownedDlcs.length === 0) {
    btn.style.display = 'none';
    return;
  }
  btn.style.display = 'flex';
  const allSelected = unownedDlcs.every(d => state.checkoutState.selectedDlcIds.has(d.dlc_id));
  if (allSelected) {
    btn.textContent = 'Deselect All DLCs';
    btn.classList.add('all-selected');
  } else {
    btn.textContent = 'Select All DLCs (Bundle)';
    btn.classList.remove('all-selected');
  }
}

function updateCheckoutSummary() {
  let total = 0.0;
  let itemCount = 0;

  if (state.checkoutState.includeBase && !state.checkoutState.isBaseOwned) {
    total += state.checkoutState.basePrice;
    itemCount++;
  }

  state.checkoutState.dlcs.forEach(d => {
    if (state.checkoutState.selectedDlcIds.has(d.dlc_id) && !d.is_owned) {
      total += d.price;
      itemCount++;
    }
  });

  const priceEl = document.getElementById('checkout-total-price');
  const countEl = document.getElementById('checkout-items-count');
  const btn = document.getElementById('btn-confirm-checkout');

  if (priceEl) priceEl.textContent = `$${total.toFixed(2)}`;
  if (countEl) countEl.textContent = `(${itemCount} item${itemCount === 1 ? '' : 's'})`;

  if (btn) {
    btn.disabled = (itemCount === 0);
    btn.textContent = itemCount === 0 ? 'Select Items to Buy' : `Buy Now ($${total.toFixed(2)})`;
  }
}

function closeGameModal() {
  document.getElementById('game-modal-overlay').classList.remove('active');
  const panel = document.getElementById('ai-bundle-panel');
  if (panel) panel.style.display = 'none';
  state.activeGameModal = null;
  state.checkoutState = null;
  state.activeBundleAiData = null;
}

function closeModalOnBackdrop(e) {
  if (e.target.id === 'game-modal-overlay') {
    closeGameModal();
  }
}

// ----------------- AI Dynamic Bundle Builder & Cart Optimizer -----------------
async function openAiBundleOptimizer() {
  if (!state.checkoutState) return;
  const panel = document.getElementById('ai-bundle-panel');
  if (!panel) return;

  panel.style.display = 'block';

  try {
    const res = await fetch(`/api/ai/bundle-optimizer?game_id=${state.checkoutState.gameId}&user_id=${state.currentUserId}`);
    if (!res.ok) throw new Error("Failed to load AI bundle optimization");
    const data = await res.json();
    state.activeBundleAiData = data;
    switchAiBundleStrategy('story');
  } catch (err) {
    console.error("AI Bundle optimizer error:", err);
    showToast("Could not load AI bundle optimizer", "error");
  }
}

function toggleAiBundlePanel(forceOpen) {
  const panel = document.getElementById('ai-bundle-panel');
  if (panel) {
    if (typeof forceOpen === 'boolean') {
      panel.style.display = forceOpen ? 'block' : 'none';
    } else {
      panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    }
  }
}

function switchAiBundleStrategy(stratId) {
  if (!state.activeBundleAiData || !state.activeBundleAiData.strategies[stratId]) return;
  state.currentAiBundleStrat = stratId;
  const strat = state.activeBundleAiData.strategies[stratId];

  // Update tabs active state
  document.querySelectorAll('.ai-bundle-tab').forEach(tab => tab.classList.remove('active'));
  const activeTab = document.getElementById(`tab-strat-${stratId}`);
  if (activeTab) activeTab.classList.add('active');

  // Update content
  const headlineEl = document.getElementById('ai-bundle-headline');
  const savingsEl = document.getElementById('ai-bundle-savings');
  const priceEl = document.getElementById('ai-bundle-price');
  const reasonEl = document.getElementById('ai-bundle-reasoning');

  if (headlineEl) headlineEl.textContent = strat.headline;
  if (savingsEl) {
    if (strat.savings > 0) {
      savingsEl.style.display = 'inline-block';
      savingsEl.textContent = `Saves $${strat.savings.toFixed(2)}`;
    } else {
      savingsEl.style.display = 'none';
    }
  }
  if (priceEl) priceEl.textContent = `$${strat.bundle_total.toFixed(2)}`;
  if (reasonEl) reasonEl.textContent = strat.reasoning;
}

function applyCurrentAiBundleStrategy() {
  if (!state.activeBundleAiData || !state.checkoutState) return;
  const strat = state.activeBundleAiData.strategies[state.currentAiBundleStrat || 'story'];
  if (!strat) return;

  // Apply base game inclusion
  state.checkoutState.includeBase = strat.include_base;
  const baseChk = document.getElementById('check-base-game');
  const baseCard = document.getElementById('card-base-game');
  if (baseChk) baseChk.checked = strat.include_base;
  if (baseCard) {
    if (strat.include_base) baseCard.classList.add('selected');
    else baseCard.classList.remove('selected');
  }

  // Apply selected DLCs
  state.checkoutState.selectedDlcIds = new Set(strat.selected_dlc_ids);
  renderDlcsList();
  updateCheckoutSummary();

  const savingsMsg = strat.savings > 0 ? ` (Saved $${strat.savings.toFixed(2)} on non-essential content!)` : '';
  showToast(`✨ AI Bundle Applied: ${strat.headline}${savingsMsg}`, "success");
}

// ----------------- Atomic Primary Checkout -----------------
async function executeCheckout() {
  if (!state.checkoutState) return;

  const payload = {
    user_id: state.currentUserId,
    game_id: state.checkoutState.gameId,
    include_base_game: state.checkoutState.includeBase && !state.checkoutState.isBaseOwned,
    selected_dlc_ids: Array.from(state.checkoutState.selectedDlcIds)
  };

  try {
    const res = await fetch('/api/purchase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Checkout transaction failed");
    }

    const keyMsg = data.assigned_key ? ` | License Key: ${data.assigned_key}` : '';
    showToast(`Purchase Successful! Total: $${data.total_paid.toFixed(2)}${keyMsg}`, "success");
    closeGameModal();

    await fetchUserProfile();
    await fetchUsers();
    await fetchLibrary();
    await fetchGames();
    fetchDbStats();
    if (state.activeView === 'database') loadTable(state.activeDbTable);
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ----------------- User Library & Device DRM -----------------
async function fetchLibrary() {
  try {
    const res = await fetch(`/api/user/library?user_id=${state.currentUserId}`);
    if (!res.ok) throw new Error("Failed to load library");
    state.library = await res.json();

    const badge = document.getElementById('library-count-badge');
    if (badge) badge.textContent = state.library.length;
    renderLibraryGrid(state.library);
  } catch (err) {
    console.error("Library load error:", err);
  }
}

function onDeviceChange() {
  const deviceSelect = document.getElementById('device-node-select');
  const currentDevice = deviceSelect ? deviceSelect.value : 'Desktop-PC-Rig';
  renderLibraryGrid(state.library);
  showToast(`Active Device Node switched to [${currentDevice}]`, "info");
}

function renderLibraryGrid(items) {
  const container = document.getElementById('library-grid-container');
  if (!container) return;
  container.innerHTML = '';

  const deviceSelect = document.getElementById('device-node-select');
  const currentDevice = deviceSelect ? deviceSelect.value : 'Desktop-PC-Rig';

  if (!items || items.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 4rem 1rem;">
        <div style="font-size: 1.2rem; font-weight: 700; color: #fff; margin-bottom: 0.5rem;">Your library is empty</div>
        <p>Explore the store catalog to claim game licenses and DLCs.</p>
        <button class="btn-details" style="margin-top: 1rem;" onclick="switchView('store')">Browse Store</button>
      </div>
    `;
    return;
  }

  items.forEach(item => {
    const card = document.createElement('div');
    card.className = 'library-card';

    const hours = (item.playtime_minutes / 60).toFixed(1);
    
    // Per-Device State Evaluation
    const isLeaseActive = item.active_session_status === 'ACTIVE';
    const isPlayingLocally = isLeaseActive && item.active_device_name === currentDevice;
    const isPlayingRemotely = isLeaseActive && item.active_device_name !== currentDevice;

    const safeTitle = item.title.replace(/'/g, "\\'");

    const basePrice = item.base_price || 59.99;

    let imageBadgeHtml = '';
    let playBtnHtml = '';

    if (isPlayingLocally) {
      imageBadgeHtml = `<span class="library-status-badge local">● Live on this PC</span>`;
      playBtnHtml = `<button class="btn-play playing" onclick="togglePlaySession(${item.game_id}, true)">■ Exit Game</button>`;
    } else if (isPlayingRemotely) {
      imageBadgeHtml = `<span class="library-status-badge remote">● Active on ${item.active_device_name}</span>`;
      playBtnHtml = `<button class="btn-play" onclick="togglePlaySession(${item.game_id}, false)">▶ Play</button>`;
    } else {
      imageBadgeHtml = '';
      playBtnHtml = `<button class="btn-play" onclick="togglePlaySession(${item.game_id}, false)">▶ Play</button>`;
    }

    const dlcPills = item.unlocked_dlcs && item.unlocked_dlcs.length > 0
      ? item.unlocked_dlcs.map(d => `<span class="dlc-pill pill-unlocked">✨ ${d.title}</span>`).join('')
      : '<span class="dlc-pill pill-base-only">Base Game Digital License</span>';

    card.innerHTML = `
      <div class="library-card-img-wrap">
        <img class="library-card-img" src="${item.header_image || item.cover_image}" alt="${item.title}">
        ${imageBadgeHtml}
      </div>
      <div class="library-card-body">
        <div class="library-edition-badge">${item.genre || 'Digital License'}</div>
        <div class="library-game-title">${item.title}</div>
        
        <div class="license-key-box">
          <span class="license-key-label">Active DRM Key</span>
          <span class="license-key-code">${item.license_code}</span>
        </div>

        <div class="library-stats-row">
          <span>Playtime: <strong>${hours} hrs</strong> (${item.playtime_minutes}m)</span>
          <span style="color: ${item.playtime_minutes <= 120 ? 'var(--accent-green)' : 'var(--text-dim)'};">
            ${item.playtime_minutes <= 120 ? 'Refund Eligible (<2h)' : 'Non-Refundable (>2h)'}
          </span>
        </div>

        <div style="font-size: 0.75rem; font-weight: 700; color: var(--text-muted); margin: 0.2rem 0 0.35rem 0;">Expansions & Entitlements:</div>
        <div class="unlocked-dlcs-tags">
          ${dlcPills}
        </div>

        <div class="library-actions" style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
          ${playBtnHtml}
          <button class="btn-sell-p2p" onclick="openSellModal(${item.library_id}, '${safeTitle}', ${basePrice}, ${item.game_id})">
            🏷️ Sell on P2P
          </button>
          <button class="btn-refund" onclick="requestRefund(${item.library_id})">
            Refund
          </button>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

// ----------------- Distributed DRM Play & Concurrency Detection -----------------
async function togglePlaySession(gameId, isCurrentlyPlaying) {
  const deviceSelect = document.getElementById('device-node-select');
  const currentDevice = deviceSelect ? deviceSelect.value : 'Desktop-PC-Rig';

  try {
    if (isCurrentlyPlaying) {
      const res = await fetch('/api/library/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: state.currentUserId, game_id: gameId })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to stop game");
      showToast(data.message, "info");
    } else {
      const res = await fetch('/api/library/play', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          user_id: state.currentUserId, 
          game_id: gameId, 
          device_name: currentDevice,
          force_takeover: false
        })
      });

      if (res.status === 409) {
        // Concurrency conflict detected! Show clean warning popup
        const conflictData = await res.json();
        const detail = conflictData.detail || {};
        openConflictModal(gameId, currentDevice, detail.active_device || "Unknown Device", detail.started_at || "Recently");
        return;
      }

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Launch failed");
      showToast(`Session active on [${currentDevice}]. Single-seat lease granted.`, "success");
    }

    await fetchLibrary();
    if (state.activeView === 'database') loadTable('active_drm_leases');
  } catch (err) {
    showToast(err.message, "error");
  }
}

function openConflictModal(gameId, requestingDevice, activeDevice, startedAt) {
  state.activeConflictGameId = gameId;
  state.activeConflictDevice = requestingDevice;

  const activeDeviceEl = document.getElementById('conflict-active-device');
  const startedAtEl = document.getElementById('conflict-started-at');
  const reqDeviceEl = document.getElementById('conflict-requesting-device');

  if (activeDeviceEl) activeDeviceEl.textContent = activeDevice;
  if (startedAtEl) startedAtEl.textContent = startedAt;
  if (reqDeviceEl) reqDeviceEl.textContent = requestingDevice;

  const overlay = document.getElementById('conflict-modal-overlay');
  if (overlay) overlay.classList.add('active');
}

function closeConflictModal() {
  const overlay = document.getElementById('conflict-modal-overlay');
  if (overlay) overlay.classList.remove('active');
  state.activeConflictGameId = null;
  state.activeConflictDevice = null;
}

function closeConflictModalOnBackdrop(e) {
  if (e.target.id === 'conflict-modal-overlay') {
    closeConflictModal();
  }
}

async function requestRefund(libraryId) {
  if (!confirm("Confirm refund request? Base game key and DLCs will be revoked and funds returned to wallet.")) return;

  try {
    const res = await fetch('/api/library/refund', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: state.currentUserId, library_id: libraryId })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Refund failed");

    showToast(data.message, "success");
    await fetchUserProfile();
    await fetchUsers();
    await fetchLibrary();
    await fetchGames();
    fetchDbStats();
    if (state.activeView === 'database') loadTable('refund_requests');
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ----------------- P2P Secondary Resale Marketplace -----------------
async function fetchMarketplace() {
  try {
    const res = await fetch('/api/marketplace');
    if (!res.ok) throw new Error("Failed to load marketplace listings");
    state.marketplace = await res.json();

    const badge = document.getElementById('marketplace-count-badge');
    if (badge) badge.textContent = state.marketplace.length;

    renderMarketplaceGrid(state.marketplace);
  } catch (err) {
    console.error("Marketplace fetch error:", err);
  }
}

function renderMarketplaceGrid(listings) {
  const container = document.getElementById('marketplace-grid-container');
  if (!container) return;
  container.innerHTML = '';

  if (!listings || listings.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 4rem 1rem;">
        <div style="font-size: 1.25rem; font-weight: 700; color: #fff; margin-bottom: 0.5rem;">No games currently listed on P2P Resale</div>
        <p>You can list your owned games from your Library at any custom price!</p>
        <button class="btn-details" style="margin-top: 1rem;" onclick="switchView('library')">Go to Library</button>
      </div>
    `;
    return;
  }

  listings.forEach(listing => {
    const card = document.createElement('div');
    card.className = 'marketplace-card';

    const discountPct = Math.round(((listing.retail_price - listing.asking_price) / listing.retail_price) * 100);
    const isOwner = listing.seller_id === state.currentUserId;

    card.innerHTML = `
      <div class="marketplace-img-wrap">
        <img class="marketplace-img" src="${listing.cover_image}" alt="${listing.game_title}">
        <span class="marketplace-tag-resale">P2P Verified</span>
        ${discountPct > 0 ? `<span class="marketplace-discount-tag">${discountPct}% OFF</span>` : ''}
      </div>
      <div class="marketplace-body">
        <div class="marketplace-title">${listing.game_title}</div>
        <div class="marketplace-genre">${listing.genre}</div>

        <div class="marketplace-seller-row">
          <img class="seller-avatar-tiny" src="${listing.seller_avatar || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=120'}" alt="${listing.seller_name}">
          <div class="seller-meta">
            <span class="seller-label">Seller</span>
            <span class="seller-name">${listing.seller_name}</span>
          </div>
        </div>

        <div class="marketplace-key-preview">
          Key ID: #${listing.key_id} &bull; <code>${listing.license_code}</code>
        </div>

        ${listing.ai_evaluation ? `
          <div class="marketplace-ai-box">
            <div class="marketplace-ai-pill-row">
              <span class="marketplace-ai-pill ${listing.ai_evaluation.badge_type}">
                ${listing.ai_evaluation.deal_label || listing.ai_evaluation.badge_label}
              </span>
              <span class="marketplace-ai-scarcity-hint">
                ${listing.ai_evaluation.scarcity_label}
              </span>
            </div>
            <div class="marketplace-ai-note">
              🤖 ${listing.ai_evaluation.feedback}
            </div>
          </div>
        ` : ''}

        <div class="marketplace-footer">
          <div class="marketplace-price-box">
            <span class="price-strike">Retail: $${listing.retail_price.toFixed(2)}</span>
            <span class="price-resale">$${listing.asking_price.toFixed(2)}</span>
          </div>
          ${isOwner ? 
            `<button class="btn-buy-p2p" disabled>Your Listing</button>` : 
            `<button class="btn-buy-p2p" onclick="buyP2PListing(${listing.listing_id})">Buy Used</button>`
          }
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

async function buyP2PListing(listingId) {
  try {
    const res = await fetch('/api/marketplace/buy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ buyer_id: state.currentUserId, listing_id: listingId })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "P2P purchase failed");

    showToast(data.message, "success");
    await fetchUserProfile();
    await fetchUsers();
    await fetchLibrary();
    await fetchMarketplace();
    fetchDbStats();
    if (state.activeView === 'database') loadTable('p2p_marketplace_listings');
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ----------------- P2P Resale Listing Modal with AI Suggestion Engine -----------------
let aiEvalDebounceTimer = null;

async function openSellModal(libraryId, gameTitle, basePrice, gameId) {
  state.activeSellItem = { libraryId, gameTitle, basePrice, gameId, aiData: null };

  const titleEl = document.getElementById('sell-modal-game-title');
  const retailEl = document.getElementById('sell-modal-retail-price');
  const priceInput = document.getElementById('sell-price-input');

  if (titleEl) titleEl.textContent = gameTitle;
  if (retailEl) retailEl.textContent = `Original Retail: $${basePrice.toFixed(2)}`;

  // Default fallback until AI returns
  if (priceInput) priceInput.value = (basePrice * 0.7).toFixed(2);
  updateSellModalBreakdown();

  const overlay = document.getElementById('sell-modal-overlay');
  if (overlay) overlay.classList.add('active');

  // Fetch real-time AI Pricing Suggestion based on primary store stock scarcity
  try {
    const res = await fetch(`/api/ai/pricing-suggestion?game_id=${gameId}&library_id=${libraryId}`);
    if (res.ok) {
      const ai = await res.json();
      state.activeSellItem.aiData = ai;

      const pillEl = document.getElementById('ai-modal-scarcity-pill');
      const sugPriceEl = document.getElementById('ai-modal-suggested-price');
      const confEl = document.getElementById('ai-modal-confidence');
      const reasonEl = document.getElementById('ai-modal-reasoning');

      if (pillEl) {
        pillEl.textContent = ai.scarcity_label;
        pillEl.className = 'ai-scarcity-pill';
        if (ai.store_stock_count === 0) pillEl.classList.add('out-of-stock');
        else if (ai.store_stock_count === 1) pillEl.classList.add('scarce');
        else pillEl.classList.add('normal');
      }

      if (sugPriceEl) sugPriceEl.textContent = `$${ai.suggested_price.toFixed(2)}`;
      if (confEl) confEl.textContent = `${ai.confidence_pct}% Model Confidence`;
      if (reasonEl) reasonEl.textContent = ai.reasoning;

      const fastPriceEl = document.getElementById('ai-preset-fast-price');
      const profitPriceEl = document.getElementById('ai-preset-profit-price');
      if (fastPriceEl) fastPriceEl.textContent = `$${ai.fast_sale_price.toFixed(2)}`;
      if (profitPriceEl) profitPriceEl.textContent = `$${ai.max_profit_price.toFixed(2)}`;

      // Provide the AI suggestion as the starting initial input, but seller has 100% freedom to modify
      if (priceInput) {
        priceInput.value = ai.suggested_price.toFixed(2);
      }
      onSellPriceInputChanged();
    }
  } catch (err) {
    console.error("AI pricing fetch error:", err);
  }
}

function applyAiLiquidityPreset(presetKey) {
  if (!state.activeSellItem || !state.activeSellItem.aiData) return;
  const ai = state.activeSellItem.aiData;
  const priceInput = document.getElementById('sell-price-input');
  if (!priceInput) return;

  if (presetKey === 'fast') {
    priceInput.value = ai.fast_sale_price.toFixed(2);
    onSellPriceInputChanged();
    showToast(`⚡ Fast Sale applied ($${ai.fast_sale_price.toFixed(2)}): ~95% chance to sell in 1h!`, "success");
  } else if (presetKey === 'profit') {
    priceInput.value = ai.max_profit_price.toFixed(2);
    onSellPriceInputChanged();
    showToast(`💰 Max Profit applied ($${ai.max_profit_price.toFixed(2)}): Patient seller margin.`, "info");
  }
}

function onSellPriceInputChanged() {
  updateSellModalBreakdown();

  const priceInput = document.getElementById('sell-price-input');
  const price = parseFloat(priceInput ? priceInput.value : 0) || 0;

  clearTimeout(aiEvalDebounceTimer);
  aiEvalDebounceTimer = setTimeout(() => {
    evaluateAskingPriceRealtime(price);
  }, 200);
}

async function evaluateAskingPriceRealtime(price) {
  if (!state.activeSellItem) return;
  const badgeEl = document.getElementById('ai-feedback-badge');
  const scoreEl = document.getElementById('ai-feedback-deal-score');
  const textEl = document.getElementById('ai-feedback-text');

  if (price <= 0) {
    if (badgeEl) {
      badgeEl.className = 'ai-feedback-badge uncompetitive';
      badgeEl.textContent = 'Invalid Price';
    }
    if (scoreEl) scoreEl.textContent = 'Deal Rating: 0.0/10';
    if (textEl) textEl.textContent = 'Please enter an asking price above $0.00.';
    return;
  }

  try {
    const res = await fetch('/api/ai/evaluate-price', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        game_id: state.activeSellItem.gameId,
        asking_price: price,
        library_id: state.activeSellItem.libraryId
      })
    });
    if (res.ok) {
      const data = await res.json();
      if (badgeEl) {
        badgeEl.className = `ai-feedback-badge ${data.status_type}`;
        badgeEl.textContent = data.badge;
      }
      if (scoreEl) {
        scoreEl.textContent = data.deal_label;
      }
      if (textEl) {
        textEl.textContent = `${data.liquidity_forecast} • ${data.message}`;
      }
    }
  } catch (e) {
    console.error("Price evaluation failed:", e);
  }
}

function updateSellModalBreakdown() {
  const priceInput = document.getElementById('sell-price-input');
  const price = parseFloat(priceInput ? priceInput.value : 0) || 0;

  const sellerPayout = price * 0.8;
  const publisherRoyalty = price * 0.2;

  const sellerEl = document.getElementById('sell-modal-seller-payout');
  const pubEl = document.getElementById('sell-modal-publisher-royalty');

  if (sellerEl) sellerEl.textContent = `$${sellerPayout.toFixed(2)}`;
  if (pubEl) pubEl.textContent = `$${publisherRoyalty.toFixed(2)}`;
}

function closeSellModal() {
  const overlay = document.getElementById('sell-modal-overlay');
  if (overlay) overlay.classList.remove('active');
  state.activeSellItem = null;
}

function closeSellModalOnBackdrop(e) {
  if (e.target.id === 'sell-modal-overlay') {
    closeSellModal();
  }
}

async function submitP2PListing() {
  if (!state.activeSellItem) return;

  const priceInput = document.getElementById('sell-price-input');
  const askingPrice = parseFloat(priceInput ? priceInput.value : 0);

  if (!askingPrice || askingPrice <= 0) {
    showToast("Please enter a valid asking price greater than $0", "error");
    return;
  }

  try {
    const res = await fetch('/api/marketplace/list', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        seller_id: state.currentUserId,
        library_id: state.activeSellItem.libraryId,
        asking_price: askingPrice
      })
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Listing failed");

    closeSellModal();
    showToast(data.message, "success");
    await fetchLibrary();
    await fetchMarketplace();
    fetchDbStats();
    if (state.activeView === 'database') loadTable('p2p_marketplace_listings');
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ----------------- Live Database Inspector -----------------
async function fetchDbStats() {
  try {
    const res = await fetch('/api/db/stats');
    if (!res.ok) return;
    const stats = await res.json();

    const elGames = document.getElementById('stat-total-games');
    const elAvail = document.getElementById('stat-available-keys');
    const elAssigned = document.getElementById('stat-assigned-keys');
    const elOwned = document.getElementById('stat-owned-licenses');
    const elTx = document.getElementById('stat-total-tx');

    if (elGames) elGames.textContent = stats.total_games;
    if (elAvail) elAvail.textContent = stats.available_keys;
    if (elAssigned) elAssigned.textContent = stats.assigned_keys;
    if (elOwned) elOwned.textContent = stats.owned_games;
    if (elTx) elTx.textContent = stats.total_transactions;
  } catch (err) {
    console.error("DB stats error:", err);
  }
}

let currentTableData = {
  tableName: 'license_keys',
  rows: [],
  columns: []
};

async function loadTable(tableName, clickedBtn = null) {
  state.activeDbTable = tableName;
  currentTableData.tableName = tableName;

  const searchInput = document.getElementById('db-search-input');
  if (searchInput) searchInput.value = '';

  const tableTitle = document.getElementById('db-current-table-title');
  if (tableTitle) tableTitle.textContent = `TABLE: ${tableName}`;

  if (clickedBtn) {
    document.querySelectorAll('.db-table-btn').forEach(b => b.classList.remove('active'));
    clickedBtn.classList.add('active');
  } else {
    document.querySelectorAll('.db-table-btn').forEach(b => {
      if (b.textContent.trim() === tableName) b.classList.add('active');
      else b.classList.remove('active');
    });
  }

  const thead = document.getElementById('db-table-header');
  const tbody = document.getElementById('db-table-body');
  if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Loading table data...</td></tr>`;

  try {
    const res = await fetch(`/api/db/table/${tableName}?limit=100`);
    if (!res.ok) throw new Error("Could not load table");
    const data = await res.json();

    currentTableData.rows = data.rows || [];
    if (currentTableData.rows.length > 0) {
      let cols = Object.keys(currentTableData.rows[0]);
      // Ensure game_id is always the 1st column if present
      if (cols.includes('game_id')) {
        cols = ['game_id', ...cols.filter(c => c !== 'game_id')];
      }
      currentTableData.columns = cols;
    } else {
      currentTableData.columns = [];
    }

    updateTableRowCount(currentTableData.rows.length, currentTableData.rows.length);
    renderActiveTable(currentTableData.rows);
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="color: var(--accent-red);">${err.message}</td></tr>`;
  }
}

function updateTableRowCount(showing, total) {
  const countEl = document.getElementById('db-table-rows-count');
  if (!countEl) return;
  if (showing === total) {
    countEl.textContent = `${total} rows`;
  } else {
    countEl.textContent = `Showing ${showing} of ${total} rows`;
  }
}

function renderActiveTable(rowsToRender) {
  const thead = document.getElementById('db-table-header');
  const tbody = document.getElementById('db-table-body');
  if (!thead || !tbody) return;

  if (rowsToRender.length === 0) {
    thead.innerHTML = `<th>Status</th>`;
    tbody.innerHTML = `<tr><td style="color: var(--text-dim); text-align: center; padding: 2rem;">No matching records found.</td></tr>`;
    return;
  }

  const columns = currentTableData.columns;
  thead.innerHTML = columns.map(col => {
    if (col === 'game_id') return `<th style="color: #58a6ff; font-weight: 800;">game_id ✦</th>`;
    return `<th>${col}</th>`;
  }).join('');

  tbody.innerHTML = rowsToRender.map(row => {
    return `<tr>` + columns.map(col => {
      let val = row[col];
      if (val === null || val === undefined) {
        val = `<span style="color: var(--text-dim);">NULL</span>`;
      } else if (col === 'game_id') {
        val = `<span style="font-family: monospace; font-weight: 800; color: #58a6ff; background: #132238; padding: 2px 7px; border-radius: 4px; border: 1px solid #1f3b64;">#${val}</span>`;
      } else if (col === 'status' || col === 'lease_status' || col === 'tx_status' || col === 'decision') {
        let badgeClass = 'badge-available';
        if (val === 'ASSIGNED' || val === 'ACTIVE' || val === 'COMPLETED' || val === 'APPROVED') badgeClass = 'badge-assigned';
        if (val === 'REVOKED' || val === 'TERMINATED' || val === 'REFUNDED' || val === 'REJECTED' || val === 'SOLD') badgeClass = 'badge-revoked';
        val = `<span class="badge-status ${badgeClass}">${val}</span>`;
      } else if (col === 'license_code') {
        val = `<code style="font-family: monospace; color: #58a6ff; font-weight: 700; background: #162032; padding: 2px 6px; border-radius: 4px;">${val}</code>`;
      }
      return `<td>${val}</td>`;
    }).join('') + `</tr>`;
  }).join('');
}

function filterCurrentTable() {
  const rawQuery = (document.getElementById('db-search-input')?.value || '').trim();
  if (!rawQuery) {
    updateTableRowCount(currentTableData.rows.length, currentTableData.rows.length);
    renderActiveTable(currentTableData.rows);
    return;
  }

  const query = rawQuery.toLowerCase();
  const tokens = query.split(/\s+/).filter(Boolean);

  const filtered = currentTableData.rows.filter(row => {
    return tokens.every(token => {
      if (token.startsWith('game:') || token.startsWith('g:')) {
        const idVal = token.split(':')[1];
        return String(row.game_id) === idVal;
      }
      if (token.startsWith('dlc:') || token.startsWith('d:')) {
        const idVal = token.split(':')[1];
        return String(row.dlc_id) === idVal;
      }
      if (token.startsWith('key:') || token.startsWith('k:')) {
        const idVal = token.split(':')[1];
        return String(row.key_id) === idVal || String(row.license_code || '').toLowerCase().includes(idVal);
      }

      if (/^\d+$/.test(token)) {
        if (String(row.game_id) === token) return true;
        if (String(row.dlc_id) === token) return true;
        if (String(row.key_id) === token) return true;
        if (String(row.user_id) === token) return true;
      }

      return Object.values(row).some(val => {
        if (val === null || val === undefined) return false;
        return String(val).toLowerCase().includes(token);
      });
    });
  });

  updateTableRowCount(filtered.length, currentTableData.rows.length);
  renderActiveTable(filtered);
}

async function refreshCurrentTable() {
  await fetchDbStats();
  await loadTable(currentTableData.tableName);
  showToast(`Refreshed ${currentTableData.tableName}`, "info");
}

async function runCustomSql(e) {
  e.preventDefault();
  const query = document.getElementById('custom-sql-input').value.trim();
  const thead = document.getElementById('sql-header');
  const tbody = document.getElementById('sql-body');

  tbody.innerHTML = `<tr><td style="color: var(--text-muted);">Executing query...</td></tr>`;

  try {
    const res = await fetch('/api/db/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Query error");

    if (data.rows.length === 0) {
      thead.innerHTML = `<th>Result</th>`;
      tbody.innerHTML = `<tr><td style="color: var(--text-dim);">Query executed successfully. 0 rows returned.</td></tr>`;
      return;
    }

    const columns = Object.keys(data.rows[0]);
    thead.innerHTML = columns.map(c => `<th>${c}</th>`).join('');
    tbody.innerHTML = data.rows.map(row => {
      return `<tr>` + columns.map(c => `<td>${row[c] !== null ? row[c] : 'NULL'}</td>`).join('') + `</tr>`;
    }).join('');

  } catch (err) {
    thead.innerHTML = `<th>Error</th>`;
    tbody.innerHTML = `<tr><td style="color: var(--accent-red);">${err.message}</td></tr>`;
  }
}

// ----------------- Toast Notifications -----------------
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(50px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ----------------- Keyboard Shortcuts (ESC Key to dismiss any open modal) -----------------
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' || e.key === 'Esc') {
    closeGameModal();
    closeSellModal();
    closeConflictModal();
  }
});

// ----------------- Database Factory Reset -----------------
async function resetDatabaseConfirm() {
  const ok = confirm("⚠️ Confirm Database Reset?\n\nThis will re-initialize all tables, restore stock, and revert all user accounts to default factory seeds.");
  if (!ok) return;

  try {
    const res = await fetch('/api/db/reset', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Reset failed");

    showToast("Database successfully restored to default state!", "success");
    await fetchUserProfile();
    await fetchUsers();
    await fetchGames();
    await fetchLibrary();
    await fetchMarketplace();
    fetchDbStats();
    if (state.activeView === 'database') loadTable(state.activeDbTable);
  } catch (err) {
    showToast(err.message, "error");
  }
}

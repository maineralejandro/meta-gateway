import React, { useState, useEffect, useCallback } from 'react'
import { useCatalog } from '../hooks/useCatalog'
import { authFetch } from '../lib/auth'
import type { CatalogItem, CatalogOption, Promotion } from '../lib/types'

type SubTab = 'items' | 'options' | 'promotions' | 'import'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'

const PROMOTION_TYPES = ['fixed_price', 'percentage', 'bogo', 'bundle', 'flat_discount', 'other']

export default function CatalogManager() {
  const catalog = useCatalog()
  const [activeTab, setActiveTab] = useState<SubTab>('items')
  const [filterCategory, setFilterCategory] = useState('')
  const [editingItem, setEditingItem] = useState<CatalogItem | null>(null)
  const [showItemModal, setShowItemModal] = useState(false)
  const [isNewItem, setIsNewItem] = useState(false)
  const [importJson, setImportJson] = useState('')
  const [importClear, setImportClear] = useState(false)
  const [saving, setSaving] = useState(false)
  const [successMsg, setSuccessMsg] = useState('')
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => { catalog.loadAll() }, [])

  const categories = Array.from(new Set(catalog.items.map(i => i.category))).sort()

  const filteredItems = filterCategory
    ? catalog.items.filter(i => i.category === filterCategory)
    : catalog.items

  const handleNewItem = () => {
    setEditingItem({
      key: '', name: '', price: 0, category: 'general', subcategory: '',
      description: '', tags: [], size: '', specifications: '',
      is_available: true, sort_order: 0, base_price: null, image_url: null, variants: [],
    })
    setIsNewItem(true)
    setShowItemModal(true)
  }

  const handleEditItem = (item: CatalogItem) => {
    setEditingItem({ ...item })
    setIsNewItem(false)
    setShowItemModal(true)
  }

  const handleSaveItem = async () => {
    if (!editingItem) return
    setSaving(true)
    setErrorMsg('')
    try {
      if (isNewItem) {
        await catalog.createItem(editingItem)
        setSuccessMsg('Item creado')
      } else {
        await catalog.updateItem(editingItem.key, editingItem)
        setSuccessMsg('Item actualizado')
      }
      setShowItemModal(false)
      await catalog.loadItems()
    } catch (e: any) {
      setErrorMsg(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteItem = async (key: string) => {
    if (!confirm(`Eliminar item "${key}"?`)) return
    try {
      await catalog.deleteItem(key)
      await catalog.loadItems()
      setSuccessMsg('Item eliminado')
    } catch (e: any) {
      setErrorMsg(e.message)
    }
  }

  const handleToggleAvailable = async (item: CatalogItem) => {
    try {
      await catalog.updateItem(item.key, { is_available: !item.is_available } as any)
      await catalog.loadItems()
    } catch (e: any) {
      setErrorMsg(e.message)
    }
  }

  const handleBulkImport = async () => {
    setSaving(true)
    setErrorMsg('')
    try {
      const data = JSON.parse(importJson)
      const result = await catalog.bulkImport(data, importClear)
      setSuccessMsg(`Importados: ${result.items} items, ${result.variants} variantes, ${result.options} opciones, ${result.promotions} promociones`)
      await catalog.loadAll()
    } catch (e: any) {
      setErrorMsg(e.message || 'JSON invalido')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-900 text-gray-100 overflow-hidden">
      <div className="p-6 border-b border-gray-800 flex justify-between items-center bg-gray-900/50 backdrop-blur-md sticky top-0 z-10">
        <div>
          <h2 className="text-2xl font-bold bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">Catalogo</h2>
          <p className="text-gray-400 text-sm">Gestiona productos, opciones y promociones</p>
        </div>
      </div>

      <div className="flex gap-1 px-6 pt-4 border-b border-gray-800">
        {(['items', 'options', 'promotions', 'import'] as SubTab[]).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-all ${activeTab === tab ? 'bg-gray-800 text-emerald-400 border border-gray-700 border-b-0' : 'text-gray-400 hover:text-gray-200'}`}
          >
            {tab === 'items' ? 'Productos' : tab === 'options' ? 'Opciones' : tab === 'promotions' ? 'Promociones' : 'Importar JSON'}
          </button>
        ))}
      </div>

      {successMsg && (
        <div className="mx-6 mt-4 p-3 bg-emerald-900/20 border border-emerald-500/30 text-emerald-400 rounded-xl text-sm flex justify-between">
          <span>{successMsg}</span>
          <button onClick={() => setSuccessMsg('')} className="text-emerald-500 hover:text-emerald-300">✕</button>
        </div>
      )}
      {errorMsg && (
        <div className="mx-6 mt-4 p-3 bg-red-900/20 border border-red-500/30 text-red-400 rounded-xl text-sm flex justify-between">
          <span>{errorMsg}</span>
          <button onClick={() => setErrorMsg('')} className="text-red-500 hover:text-red-300">✕</button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
        {activeTab === 'items' && (
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <div className="flex gap-3 items-center">
                <select
                  value={filterCategory}
                  onChange={e => setFilterCategory(e.target.value)}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
                >
                  <option value="">Todas las categorias</option>
                  {categories.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <span className="text-xs text-gray-500">{filteredItems.length} items</span>
              </div>
              <button onClick={handleNewItem} className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-sm font-medium transition-all">
                + Nuevo Producto
              </button>
            </div>

            <div className="bg-gray-800/30 rounded-xl border border-gray-700 overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-700">
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Key</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Nombre</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Categoria</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Precio</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Disponible</th>
                    <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map(item => (
                    <tr key={item.key} className="border-b border-gray-700/50 hover:bg-gray-800/30 transition-colors">
                      <td className="px-4 py-3 font-mono text-xs text-gray-400">{item.key}</td>
                      <td className="px-4 py-3 text-sm text-gray-200">{item.name}</td>
                      <td className="px-4 py-3"><span className="px-2 py-0.5 bg-gray-700 rounded text-xs text-gray-300">{item.category}</span></td>
                      <td className="px-4 py-3 text-sm text-gray-300">${item.price.toLocaleString()}</td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => handleToggleAvailable(item)}
                          className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${item.is_available ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}
                        >
                          {item.is_available ? 'Si' : 'No'}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-right space-x-2">
                        <button onClick={() => handleEditItem(item)} className="text-xs text-emerald-400 hover:text-emerald-300">Editar</button>
                        <button onClick={() => handleDeleteItem(item.key)} className="text-xs text-red-400 hover:text-red-300">Eliminar</button>
                      </td>
                    </tr>
                  ))}
                  {filteredItems.length === 0 && (
                    <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">No hay items</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === 'options' && (
          <div className="space-y-4">
            <div className="bg-gray-800/30 rounded-xl border border-gray-700 overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-700">
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Key</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Nombre</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Precio</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Scope</th>
                  </tr>
                </thead>
                <tbody>
                  {catalog.options.map(opt => (
                    <tr key={opt.key} className="border-b border-gray-700/50 hover:bg-gray-800/30">
                      <td className="px-4 py-3 font-mono text-xs text-gray-400">{opt.key}</td>
                      <td className="px-4 py-3 text-sm text-gray-200">{opt.name}</td>
                      <td className="px-4 py-3 text-sm text-gray-300">${opt.price.toLocaleString()}</td>
                      <td className="px-4 py-3"><span className="px-2 py-0.5 bg-gray-700 rounded text-xs text-gray-300">{opt.category_scope}</span></td>
                    </tr>
                  ))}
                  {catalog.options.length === 0 && (
                    <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-500">No hay opciones</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === 'promotions' && (
          <div className="space-y-4">
            <div className="bg-gray-800/30 rounded-xl border border-gray-700 overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-700">
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Key</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Nombre</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Tipo</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Precio</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Texto</th>
                  </tr>
                </thead>
                <tbody>
                  {catalog.promotions.map(promo => (
                    <tr key={promo.key} className="border-b border-gray-700/50 hover:bg-gray-800/30">
                      <td className="px-4 py-3 font-mono text-xs text-gray-400">{promo.key}</td>
                      <td className="px-4 py-3 text-sm text-gray-200">{promo.name}</td>
                      <td className="px-4 py-3"><span className="px-2 py-0.5 bg-gray-700 rounded text-xs text-gray-300">{promo.promotion_type}</span></td>
                      <td className="px-4 py-3 text-sm text-gray-300">{promo.price ? `$${promo.price.toLocaleString()}` : '-'}</td>
                      <td className="px-4 py-3 text-sm text-gray-400">{promo.display_text || '-'}</td>
                    </tr>
                  ))}
                  {catalog.promotions.length === 0 && (
                    <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-500">No hay promociones</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === 'import' && (
          <div className="space-y-4 max-w-2xl">
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-400">JSON del catalogo</label>
              <textarea
                value={importJson}
                onChange={e => setImportJson(e.target.value)}
                rows={16}
                placeholder='{"catalog_items": [{"key": "item_1", "name": "Item 1", "price": 1000, "category": "food"}]}'
                className="w-full bg-gray-950/50 border border-gray-800 rounded-xl px-4 py-3 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500/40 text-gray-300 shadow-inner"
              />
            </div>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-sm text-gray-400">
                <input
                  type="checkbox"
                  checked={importClear}
                  onChange={e => setImportClear(e.target.checked)}
                  className="rounded border-gray-600 bg-gray-800"
                />
                Limpiar datos existentes antes de importar
              </label>
            </div>
            <button
              onClick={handleBulkImport}
              disabled={saving || !importJson.trim()}
              className="px-6 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg font-medium transition-all"
            >
              {saving ? 'Importando...' : 'Importar'}
            </button>
          </div>
        )}
      </div>

      {showItemModal && editingItem && (
        <ItemEditModal
          item={editingItem}
          isNew={isNewItem}
          saving={saving}
          onSave={handleSaveItem}
          onClose={() => setShowItemModal(false)}
          onChange={setEditingItem}
        />
      )}

      <style jsx>{`
        .custom-scrollbar::-webkit-scrollbar { width: 6px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #1f2937; border-radius: 10px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #374151; }
      `}</style>
    </div>
  )
}

interface ItemModalProps {
  item: CatalogItem
  isNew: boolean
  saving: boolean
  onSave: () => void
  onClose: () => void
  onChange: (item: CatalogItem) => void
}

function ItemEditModal({ item, isNew, saving, onSave, onClose, onChange }: ItemModalProps) {
  const handleFieldChange = (field: keyof CatalogItem, value: any) => {
    onChange({ ...item, [field]: value })
  }

  const handleTagsChange = (text: string) => {
    onChange({ ...item, tags: text.split(',').map(t => t.trim()).filter(Boolean) })
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-2xl max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-6">
          <h3 className="text-lg font-semibold text-gray-200">{isNew ? 'Nuevo Producto' : 'Editar Producto'}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-200 text-xl">&times;</button>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-500 uppercase">Key</label>
              <input
                value={item.key}
                onChange={e => handleFieldChange('key', e.target.value)}
                disabled={!isNew}
                className="w-full bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40 disabled:opacity-50 font-mono"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-500 uppercase">Nombre</label>
              <input
                value={item.name}
                onChange={e => handleFieldChange('name', e.target.value)}
                className="w-full bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-500 uppercase">Precio</label>
              <input
                type="number"
                value={item.price}
                onChange={e => handleFieldChange('price', parseInt(e.target.value) || 0)}
                className="w-full bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-500 uppercase">Categoria</label>
              <input
                value={item.category}
                onChange={e => handleFieldChange('category', e.target.value)}
                className="w-full bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-500 uppercase">Subcategoria</label>
              <input
                value={item.subcategory}
                onChange={e => handleFieldChange('subcategory', e.target.value)}
                className="w-full bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-gray-500 uppercase">Descripcion</label>
            <textarea
              value={item.description}
              onChange={e => handleFieldChange('description', e.target.value)}
              rows={2}
              className="w-full bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-500 uppercase">Tags (comma-separated)</label>
              <input
                value={item.tags.join(', ')}
                onChange={e => handleTagsChange(e.target.value)}
                className="w-full bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-500 uppercase">Tamano</label>
              <input
                value={item.size}
                onChange={e => handleFieldChange('size', e.target.value)}
                className="w-full bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
              />
            </div>
          </div>

          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-gray-400">
              <input
                type="checkbox"
                checked={item.is_available}
                onChange={e => handleFieldChange('is_available', e.target.checked)}
                className="rounded border-gray-600 bg-gray-800"
              />
              Disponible
            </label>
          </div>

          {item.variants.length > 0 && (
            <div className="space-y-2">
              <label className="text-xs font-medium text-gray-500 uppercase">Variantes ({item.variants.length})</label>
              {item.variants.map((v, i) => (
                <div key={i} className="flex gap-2 items-center bg-gray-800/30 rounded-lg px-3 py-2">
                  <span className="text-xs text-gray-400 font-mono">{v.slug}</span>
                  <span className="text-sm text-gray-300">{v.label}</span>
                  <span className="text-sm text-gray-400 ml-auto">${v.price.toLocaleString()}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-3 mt-6 pt-4 border-t border-gray-700">
          <button onClick={onClose} className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg text-sm transition-all border border-gray-700">
            Cancelar
          </button>
          <button
            onClick={onSave}
            disabled={saving || !item.key || !item.name}
            className="px-6 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg font-medium transition-all"
          >
            {saving ? 'Guardando...' : isNew ? 'Crear' : 'Guardar'}
          </button>
        </div>
      </div>
    </div>
  )
}

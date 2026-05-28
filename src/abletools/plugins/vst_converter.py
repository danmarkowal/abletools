from pathlib import Path


from lxml import etree


from abletools.plugins.component_extractor import Uid
from abletools.plugins.plugin_data_converter import PluginDataConverter
from abletools.plugins.vst_id_converter import VstIdConversionError, VstIdConverter
from abletools.utils.xml_converter import XMLConversionError, XMLConverter, copy_tags, find_not_null, format_long_text_element, get_tagged_value, make_tagged_value, map_tag


class VstConversionContext:
    def __init__(self, uid_cache_path: Path):
        self._uid_cache_path = uid_cache_path

    @property
    def uid_cache_path(self):
        return self._uid_cache_path


class Vst3Converter(XMLConverter):
    # These tags are the same in VST2 and VST3 plugin info, so we can just copy them over without modification
    SAME_TAGS = ["WinPosX", "WinPosY", "NumAudioInputs",
                 "NumAudioOutputs", "IsPlaceholderDevice"]

    def __init__(self, ctx: VstConversionContext):
        self.ctx = ctx

    def convert(self, root: etree.Element) -> etree.Element:
        # <Vst3PluginInfo Id="12345">
        vst3_info = etree.Element("Vst3PluginInfo")
        # IDK whether you can have more than one Vst3PluginInfo in a plugin descriptor tag
        vst3_info.set("Id", root.get("Id", "0"))

        plugin_path = get_tagged_value(root, "Path", Path)
        plugin_version = get_tagged_value(root, "Version", int)

        copy_tags(root, vst3_info, self.SAME_TAGS)

        try:
            uid = VstIdConverter(self.ctx.uid_cache_path).convert_to_uid(
                plugin_path, plugin_version)
        except VstIdConversionError as e:
            raise XMLConversionError(
                f"Failed to convert UID of VST2 plugin at path '{plugin_path}'. Error {e}")

        # <Preset Id="12345">
        vst3_info.append(
            VstPresetConverter(uid).convert(find_not_null(root, "Preset")))

        # <Name>
        map_tag(root, vst3_info, "PlugName", "Name")

        # <Uid>
        vst3_info.append(_make_uid_element(uid))

        return vst3_info


class VstPresetConverter(XMLConverter):
    # These go before the Processor and Controller states
    # I'm not sure if the order matters, but we might as well keep it consistent
    SAME_TAGS_1 = ["OverwriteProtectionNumber",
                   "MpeEnabled", "MpeSettings",
                   "ParameterSettings", "IsOn",
                   "PowerMacroControlIndex",
                   "PowerMacroMappingRange",
                   "IsFolded",
                   "StoredAllParameters",
                   "DeviceLomId",
                   "DeviceViewLomId",
                   "IsOnLomId",
                   "ParametersListWrapperLomId"]
    # These go after the Processor and Controller states
    SAME_TAGS_2 = ["Name", "PresetRef"]

    def __init__(self, uid: Uid):
        self.uid = uid

    def convert(self, root: etree.Element) -> etree.Element:
        # root:
        #   <Preset>
        #       <VstPreset Id="12345">
        #       ...
        #       </VstPreset>
        #   </Preset>
        vst2_preset = find_not_null(root, "VstPreset")
        vst3_preset = etree.Element("Vst3Preset")
        vst3_preset.set("Id", vst2_preset.get("Id", "0"))

        # Extract values BEFORE copying tags to present missing tag errors
        plugin_id = get_tagged_value(vst2_preset, "UniqueId", int)
        plugin_version = get_tagged_value(vst2_preset, "PluginVersion", int)
        program_number = get_tagged_value(vst2_preset, "ProgramNumber", int)
        is_on = get_tagged_value(vst2_preset, "IsOn", _ableton_bool)

        # First set of common tags
        copy_tags(vst2_preset, vst3_preset, self.SAME_TAGS_1)

        # Add <Uid>
        vst3_preset.append(_make_uid_element(self.uid))

        # Add <DeviceType>

        # Add <ProcessorState>
        plugin_data = VstPluginDataConverter(plugin_id, plugin_version,
                                             program_number, not is_on).convert(find_not_null(vst2_preset, "Buffer"))
        format_long_text_element(plugin_data)
        vst3_preset.append(plugin_data)

        # Add <ControllerState> (IDK whether this is supposed to have any contents)
        vst3_preset.append(etree.Element("ControllerState"))

        # Second set of common tags
        copy_tags(vst2_preset, vst3_preset, self.SAME_TAGS_2)

        new_preset = etree.Element("Preset")
        new_preset.append(vst3_preset)
        return new_preset


class VstPluginDataConverter(XMLConverter):
    def __init__(self, vst2_unique_id: int, plugin_version: int, current_program: int, is_bypassed: bool):
        """
        :param vst2_unique_id: `<UniqueId>`
        :param plugin_version: `<Version>`
        :param current_program: `<ProgramNumber>`
        :param is_bypassed: `<IsOn>`
        """
        self.vst2_unique_id = vst2_unique_id
        self.plugin_version = plugin_version
        self.current_program = current_program
        self.is_bypassed = is_bypassed

    def convert(self, root: etree.Element) -> etree.Element:
        # root:
        #   <Buffer>
        #     ... (buffer data)
        #   </Buffer>
        buffer_contents = root.text
        if buffer_contents is None:
            raise XMLConversionError(
                f"Buffer contents for element '{root.getroottree().getpath(root)}' are empty.")

        buffer_contents = self._sanitize_buffer_contents(buffer_contents)

        vst3_state = etree.Element("ProcessorState")
        vst3_state.text = PluginDataConverter().convert_to_processor_state(buffer_contents)
        return vst3_state

    def _sanitize_buffer_contents(self, buffer_contents: str) -> str:
        # We need to remove spaces, newlines, tabs etc. so that binascii doesn't complain
        return "".join(buffer_contents.split())


def _make_uid_element(uid_fields: Uid) -> etree.Element:
    uid_element = etree.Element("Uid")
    for i, field in enumerate(uid_fields):
        uid_element.append(make_tagged_value(f"Fields.{i}", str(field)))
    return uid_element


def _ableton_bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"Ableton boolean must be either 'true' or 'false'.")
